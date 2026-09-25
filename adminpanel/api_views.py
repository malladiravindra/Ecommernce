"""Admin-only REST API (/api/admin/...).

Every view requires an authenticated ADMIN-side user (staff or super admin).
Customers get 403, anonymous users 401/403. Admins manage products,
categories, inventory and orders; they can view — but never create —
customer accounts, and can never change payment status.
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, DecimalField, ProtectedError, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import timedelta

from django.db.models import F
from django.db.models.functions import TruncDate
from rest_framework import serializers
from django.utils import timezone
from django.utils.dateparse import parse_date

from shop import services
from shop.models import Category, Offer, Order, OrderItem, Payment, Product, ProductImage
from shop.offers import attach_offers
from shop.rbac import IsAdminRole
from shop.serializers import (
    AdminOfferSerializer, AdminOrderSerializer, AdminProductSerializer, PaymentSummarySerializer, ProductImageSerializer,
)

from .serializers import (
    AdminCategorySerializer,
    AdminCustomerSerializer,
    ProductStockSerializer,
    validate_image_size,
)

LOW_STOCK_THRESHOLD = 5
PRODUCT_SORTS = {
    'newest': '-created_at', 'oldest': 'created_at', 'name': 'name',
    'price_low': 'price', 'price_high': '-price', 'stock_low': 'stock', 'stock_high': '-stock',
}


class AdminPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def paginate(self, request, queryset, serializer_class, prepare=None):
        paginator = AdminPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if prepare:
            prepare(page)
        return paginator.get_paginated_response(serializer_class(page, many=True, context={'request': request}).data)


def customers_queryset():
    return User.objects.filter(is_staff=False, is_superuser=False)


def paid_revenue_filter(prefix=''):
    return Q(**{f'{prefix}payment_status': True}) & ~Q(**{f'{prefix}status': Order.CANCELLED})


# ─────────────────────────── Dashboard ───────────────────────────

class DashboardAPIView(AdminAPIView):
    """GET /api/admin/dashboard/ — live statistics straight from the database."""

    def get(self, request):
        products = Product.objects.all()
        orders = Order.objects.all()
        by_status = dict(orders.order_by().values_list('status').annotate(n=Count('id')))
        total_sales = orders.filter(paid_revenue_filter()).aggregate(s=Sum('total_price'))['s'] or 0
        payments_by_status = dict(Payment.objects.order_by().values_list('status').annotate(n=Count('id')))

        return Response({
            'stats': {
                'total_products': products.count(),
                'active_products': products.filter(is_active=True).count(),
                'out_of_stock_products': products.filter(stock=0).count(),
                'low_stock_products': products.filter(stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD).count(),
                'total_customers': customers_queryset().count(),
                'total_orders': orders.count(),
                'pending_orders': by_status.get(Order.PENDING, 0),
                'delivered_orders': by_status.get(Order.DELIVERED, 0),
                'total_sales': total_sales,
                'new_launch_products': products.filter(is_new_launch=True).count(),
                'active_offers': Offer.objects.active().count(),
                'refunds_required': Payment.objects.filter(refund_status=Payment.REFUND_REQUIRED).count(),
            },
            'payments_by_status': [
                {'status': code, 'label': label, 'count': payments_by_status.get(code, 0)}
                for code, label in Payment.STATUS_CHOICES
            ],
            'orders_by_status': [
                {'status': code, 'label': label, 'count': by_status.get(code, 0)}
                for code, label in Order.STATUS_CHOICES
            ],
            'recent_orders': AdminOrderSerializer(
                orders.select_related('user').prefetch_related('items', 'payments')[:8], many=True).data,
            'recent_products': ProductStockSerializer(
                products.select_related('category').order_by('-created_at')[:6], many=True, context={'request': request}).data,
            'low_stock': ProductStockSerializer(
                products.select_related('category').filter(stock__lte=LOW_STOCK_THRESHOLD).order_by('stock', 'name')[:10],
                many=True, context={'request': request}).data,
            'low_stock_threshold': LOW_STOCK_THRESHOLD,
        })


# ─────────────────────────── Products ───────────────────────────

def _save_gallery(product, files):
    """Validate every gallery file (type + size) before saving any of them."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from rest_framework import serializers as drf_serializers
    field = drf_serializers.ImageField(validators=[validate_image_size])
    errors = []
    for f in files:
        try:
            field.run_validation(f)
        except drf_serializers.ValidationError as error:
            errors.append(f"{f.name}: {' '.join(str(e) for e in error.detail)}")
        except DjangoValidationError as error:  # Pillow could not read the file
            errors.append(f"{f.name}: {' '.join(error.messages)}")
    if errors:
        raise drf_serializers.ValidationError({'images': errors})
    for f in files:
        ProductImage.objects.create(product=product, image=f)


class ProductListCreateAPIView(AdminAPIView):
    """GET  /api/admin/products/?q=&category=&status=active|inactive&stock=in|low|out&sort=&page=
    POST /api/admin/products/  (multipart: fields + optional `image` and `images` gallery files)
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        p = request.query_params
        qs = Product.objects.select_related('category').prefetch_related('images')
        if p.get('q'):
            q = p['q'].strip()
            qs = qs.filter(Q(name__icontains=q) | Q(brand__icontains=q) | Q(description__icontains=q) | Q(slug__icontains=q))
        if p.get('category'):
            qs = qs.filter(category_id=p['category'])
        if p.get('status') == 'active':
            qs = qs.filter(is_active=True)
        elif p.get('status') == 'inactive':
            qs = qs.filter(is_active=False)
        stock = p.get('stock')
        if stock == 'out':
            qs = qs.filter(stock=0)
        elif stock == 'low':
            qs = qs.filter(stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD)
        elif stock == 'in':
            qs = qs.filter(stock__gt=0)
        if p.get('new_launch') in ('1', '0'):
            qs = qs.filter(is_new_launch=p['new_launch'] == '1')
        qs = qs.order_by(PRODUCT_SORTS.get(p.get('sort'), '-created_at'))
        return self.paginate(request, qs, AdminProductSerializer, prepare=attach_offers)

    def post(self, request):
        serializer = AdminProductSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            product = serializer.save()
            _save_gallery(product, request.FILES.getlist('images'))
        return Response(AdminProductSerializer(product, context={'request': request}).data, status=status.HTTP_201_CREATED)


class ProductDetailAPIView(AdminAPIView):
    """GET/PUT/PATCH/DELETE /api/admin/products/<id>/"""
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, pk):
        product = get_object_or_404(Product.objects.select_related('category').prefetch_related('images'), pk=pk)
        return Response(AdminProductSerializer(product, context={'request': request}).data)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        product = get_object_or_404(Product, pk=pk)
        # Omitting `image` keeps the current one; `remove_image=true` clears it.
        serializer = AdminProductSerializer(product, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        extra = {}
        if str(request.data.get('remove_image', '')).lower() in ('1', 'true') and not request.FILES.get('image'):
            extra['image'] = None
        with transaction.atomic():
            product = serializer.save(**extra)
            _save_gallery(product, request.FILES.getlist('images'))
        return Response(AdminProductSerializer(product, context={'request': request}).data)

    def delete(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        if OrderItem.objects.filter(product=product).exists():
            # Products that appear in orders are archived, not destroyed, so
            # order history keeps its product link and image. (OrderItem also
            # snapshots name/price and uses SET_NULL as a second safeguard.)
            if product.is_active:
                product.is_active = False
                product.save(update_fields=['is_active', 'updated_at'])
            return Response({
                'archived': True,
                'detail': 'This product appears in past orders, so it was deactivated (hidden from customers) instead of deleted.',
                'product': AdminProductSerializer(product, context={'request': request}).data,
            })
        product.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductImageAPIView(AdminAPIView):
    """POST   /api/admin/products/<id>/images/            (multipart `images`)
    DELETE /api/admin/products/<id>/images/<image_id>/
    """
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        files = request.FILES.getlist('images')
        if not files:
            return Response({'images': ['Select at least one image.']}, status=400)
        _save_gallery(product, files)
        return Response(ProductImageSerializer(product.images.all(), many=True, context={'request': request}).data, status=201)

    def delete(self, request, pk, image_id):
        get_object_or_404(ProductImage, pk=image_id, product_id=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────── Categories ───────────────────────────

class CategoryListCreateAPIView(AdminAPIView):
    """GET /api/admin/categories/ (with product counts) · POST /api/admin/categories/"""
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        qs = Category.objects.annotate(product_count=Count('products')).order_by('name')
        return Response(AdminCategorySerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = AdminCategorySerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CategoryDetailAPIView(AdminAPIView):
    """PUT/PATCH/DELETE /api/admin/categories/<id>/"""
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        category = get_object_or_404(Category, pk=pk)
        serializer = AdminCategorySerializer(category, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        count = category.products.count()
        if count:
            # Also enforced by Product.category on_delete=PROTECT.
            return Response({'error': f'Move or delete the {count} product(s) in this category first.'}, status=409)
        try:
            category.delete()
        except ProtectedError:
            return Response({'error': 'This category still has products.'}, status=409)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────── Customers (read-only) ───────────────────────────

def _customers_with_totals():
    return customers_queryset().select_related('profile').annotate(
        orders_count=Count('orders', distinct=True),
        total_spent=Coalesce(
            Sum('orders__total_price', filter=paid_revenue_filter('orders__')),
            Value(0), output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )


class CustomerListAPIView(AdminAPIView):
    """GET /api/admin/customers/?q=&page= — registered customers (no create endpoint by design)."""

    def get(self, request):
        qs = _customers_with_totals()
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        return self.paginate(request, qs.order_by('-date_joined'), AdminCustomerSerializer)


class CustomerDetailAPIView(AdminAPIView):
    """GET /api/admin/customers/<id>/ — customer summary plus their orders."""

    def get(self, request, pk):
        customer = get_object_or_404(_customers_with_totals(), pk=pk)
        orders = Order.objects.filter(user=customer).prefetch_related('items', 'payments')
        data = AdminCustomerSerializer(customer).data
        data['orders'] = AdminOrderSerializer(orders, many=True).data
        return Response(data)


# ─────────────────────────── Orders ───────────────────────────

class OrderListAPIView(AdminAPIView):
    """GET /api/admin/orders/?status=&q=&paid=1|0&page="""

    def get(self, request):
        p = request.query_params
        qs = Order.objects.select_related('user').prefetch_related('items', 'payments')
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('paid') in ('1', '0'):
            qs = qs.filter(payment_status=p['paid'] == '1')
        q = p.get('q', '').strip().lstrip('#')
        if q:
            cond = Q(user__email__icontains=q) | Q(user__username__icontains=q) | Q(tracking_number__icontains=q)
            if q.isdigit():
                cond |= Q(pk=int(q))
            qs = qs.filter(cond)
        return self.paginate(request, qs, AdminOrderSerializer)


class OrderDetailAPIView(AdminAPIView):
    """GET /api/admin/orders/<id>/"""

    def get(self, request, pk):
        order = get_object_or_404(Order.objects.select_related('user').prefetch_related('items__product', 'payments'), pk=pk)
        return Response(AdminOrderSerializer(order).data)


class OrderStatusAPIView(AdminAPIView):
    """PUT /api/admin/orders/<id>/status/ {"status", "tracking_number"?, "reason"?}

    Enforces Order.ALLOWED_TRANSITIONS. PENDING -> CONFIRMED is not allowed
    here — only a verified payment confirms an order. Cancelling a confirmed
    order restores its stock. Payment status is never editable.
    """

    def put(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        new_status = (request.data.get('status') or '').upper()
        if new_status not in dict(Order.STATUS_CHOICES):
            return Response({'status': ['Invalid status.']}, status=400)
        try:
            order = services.update_order_status(
                order, new_status,
                tracking_number=(request.data.get('tracking_number') or '').strip() or None,
                reason=(request.data.get('reason') or '').strip(),
            )
        except services.CheckoutError as error:
            return Response({'error': error.message}, status=400)
        order = Order.objects.select_related('user').prefetch_related('items__product', 'payments').get(pk=order.pk)
        return Response(AdminOrderSerializer(order).data)


# ─────────────────────────── Offers ───────────────────────────

class OfferListCreateAPIView(AdminAPIView):
    """GET /api/admin/offers/?q=&state=live|scheduled|expired|inactive · POST /api/admin/offers/"""

    def get(self, request):
        now = timezone.now()
        qs = Offer.objects.prefetch_related('products', 'categories')
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        state = request.query_params.get('state')
        if state == 'live':
            qs = qs.active(now)
        elif state == 'scheduled':
            qs = qs.filter(is_active=True, starts_at__gt=now)
        elif state == 'expired':
            qs = qs.filter(ends_at__lte=now)
        elif state == 'inactive':
            qs = qs.filter(is_active=False)
        return self.paginate(request, qs, AdminOfferSerializer)

    def post(self, request):
        serializer = AdminOfferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offer = serializer.save()
        return Response(AdminOfferSerializer(offer).data, status=status.HTTP_201_CREATED)


class OfferDetailAPIView(AdminAPIView):
    """GET/PUT/PATCH/DELETE /api/admin/offers/<id>/

    Placed orders keep the price they were bought at (OrderItem.price), so
    editing or deleting an offer never changes past orders.
    """

    def get(self, request, pk):
        return Response(AdminOfferSerializer(get_object_or_404(Offer, pk=pk)).data)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        serializer = AdminOfferSerializer(get_object_or_404(Offer, pk=pk), data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        return Response(AdminOfferSerializer(serializer.save()).data)

    def delete(self, request, pk):
        get_object_or_404(Offer, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────── Payments (read-only) ───────────────────────────

class AdminPaymentSerializer(PaymentSummarySerializer):
    order_id = serializers.IntegerField(read_only=True)
    order_status = serializers.CharField(source='order.status', read_only=True)
    customer_email = serializers.CharField(source='user.email', read_only=True, default=None)

    class Meta(PaymentSummarySerializer.Meta):
        fields = PaymentSummarySerializer.Meta.fields + ['order_id', 'order_status', 'customer_email', 'updated_at']


class PaymentListAPIView(AdminAPIView):
    """GET /api/admin/payments/?status=&refund=REQUIRED&q= — gateway payment records.

    Read-only by design: payment and refund states are only changed by
    backend verification and Razorpay webhooks.
    """

    def get(self, request):
        p = request.query_params
        qs = Payment.objects.select_related('order', 'user')
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('refund'):
            qs = qs.filter(refund_status=p['refund'])
        q = p.get('q', '').strip().lstrip('#')
        if q:
            cond = Q(provider_order_id__icontains=q) | Q(provider_payment_id__icontains=q) | Q(user__email__icontains=q)
            if q.isdigit():
                cond |= Q(order_id=int(q))
            qs = qs.filter(cond)
        return self.paginate(request, qs, AdminPaymentSerializer)


# ─────────────────────────── Reports ───────────────────────────

class ReportsAPIView(AdminAPIView):
    """GET /api/admin/reports/?from=YYYY-MM-DD&to=YYYY-MM-DD (default: last 30 days).

    Sales = paid orders that were not cancelled, by order date.
    """

    def get(self, request):
        today = timezone.localdate()
        start = parse_date(request.query_params.get('from') or '') or today - timedelta(days=29)
        end = parse_date(request.query_params.get('to') or '') or today
        if end < start:
            return Response({'error': "'to' must be on or after 'from'."}, status=400)
        if (end - start).days > 366:
            return Response({'error': 'The report range can be at most one year.'}, status=400)

        orders = Order.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        sales = orders.filter(paid_revenue_filter())
        revenue = sales.aggregate(s=Sum('total_price'))['s'] or 0
        paid_count = sales.count()
        daily = (
            sales.annotate(day=TruncDate('created_at')).values('day')
            .annotate(orders=Count('id'), revenue=Sum('total_price')).order_by('day')
        )
        top_products = (
            OrderItem.objects.filter(order__in=sales).values('product_name')
            .annotate(units=Sum('quantity'), revenue=Sum(F('price') * F('quantity'))).order_by('-units')[:10]
        )
        by_status = dict(orders.order_by().values_list('status').annotate(n=Count('id')))
        payments = Payment.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        pay_by_status = dict(payments.order_by().values_list('status').annotate(n=Count('id')))
        refunds_due = Payment.objects.filter(refund_status=Payment.REFUND_REQUIRED)

        return Response({
            'range': {'from': start, 'to': end},
            'summary': {
                'orders': orders.count(),
                'paid_orders': paid_count,
                'revenue': revenue,
                'average_order_value': (revenue / paid_count) if paid_count else 0,
                'items_sold': OrderItem.objects.filter(order__in=sales).aggregate(n=Sum('quantity'))['n'] or 0,
                'new_customers': customers_queryset().filter(date_joined__date__gte=start, date_joined__date__lte=end).count(),
                'refunds_required': refunds_due.count(),
                'refunds_required_amount': refunds_due.aggregate(s=Sum('amount'))['s'] or 0,
            },
            'daily_sales': [{'date': r['day'], 'orders': r['orders'], 'revenue': r['revenue']} for r in daily],
            'top_products': list(top_products),
            'orders_by_status': [{'status': c, 'label': l, 'count': by_status.get(c, 0)} for c, l in Order.STATUS_CHOICES],
            'payments_by_status': [{'status': c, 'label': l, 'count': pay_by_status.get(c, 0)} for c, l in Payment.STATUS_CHOICES],
        })
