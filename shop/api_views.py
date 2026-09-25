import json
import logging

from django.conf import settings
from django.db.models import Q
from rest_framework import status, permissions, generics
from rest_framework.exceptions import ValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Product, Cart, CartItem, Wishlist, Review, Category, Order, Payment, ShippingAddress, Offer
from .offers import attach_offers
from .serializers import (
    AddressSerializer,
    OfferSerializer,
    CartItemSerializer,
    CartSerializer,
    ReviewSerializer,
    CategorySerializer,
    ProductSerializer,
    WishlistSerializer,
    OrderSerializer,
)
from . import payments, services

logger = logging.getLogger(__name__)

PRODUCT_SORTS = {
    'price_low': 'price',
    'price_high': '-price',
    'newest': '-created_at',
    'name': 'name',
}


class ProductListAPIView(generics.ListAPIView):
    """GET /api/products/?q=&category=<slug|id>&min_price=&max_price=&in_stock=1&sort=price_low|price_high|newest|name"""
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        params = self.request.query_params
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images')
        if params.get('q'):
            q = params['q'].strip()
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(brand__icontains=q))
        category = params.get('category')
        if category:
            qs = qs.filter(category_id=category) if category.isdigit() else qs.filter(category__slug=category)
        try:
            if params.get('min_price'):
                qs = qs.filter(price__gte=float(params['min_price']))
            if params.get('max_price'):
                qs = qs.filter(price__lte=float(params['max_price']))
        except ValueError:
            raise ValidationError({'price': 'min_price and max_price must be numbers.'})
        if params.get('in_stock') in ('1', 'true'):
            qs = qs.filter(stock__gt=0)
        if params.get('new_launch') in ('1', 'true'):
            qs = qs.filter(is_new_launch=True)
        return qs.order_by(PRODUCT_SORTS.get(params.get('sort'), '-created_at'))

    def list(self, request, *args, **kwargs):
        products = attach_offers(list(self.get_queryset()))  # one offer query for the whole list
        return Response(self.get_serializer(products, many=True).data)


class OfferListAPIView(APIView):
    """GET /api/offers/ — currently live offers (read-only, public)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        offers = Offer.objects.active().prefetch_related('products', 'categories')
        return Response(OfferSerializer(offers, many=True).data)


class ProductDetailAPIView(generics.RetrieveAPIView):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]


class CategoryListAPIView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class CategoryDetailAPIView(generics.RetrieveAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class CartDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        serializer = CartSerializer(cart)
        return Response(serializer.data)


class WishlistListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = WishlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class WishlistDestroyAPIView(generics.DestroyAPIView):
    serializer_class = WishlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user)


class ReviewListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Review.objects.all()
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    def perform_create(self, serializer):
        product = serializer.validated_data['product']
        if Review.objects.filter(product=product, user=self.request.user).exists():
            raise ValidationError({"product": "You have already reviewed this product."})
        serializer.save(user=self.request.user)


def _checkout_error(error, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({"success": False, "error": error.message, "problems": error.problems}, status=http_status)


class OrderListCreateAPIView(APIView):
    """GET  /api/orders/  - the customer's own orders.
    POST /api/orders/  {"address_id"} - validate the cart and create a PENDING order.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(user=request.user).prefetch_related('items__product', 'payments')
        return Response(OrderSerializer(orders, many=True).data)

    def post(self, request):
        address_id = request.data.get('address_id')
        if not address_id:
            return Response({"success": False, "error": "Please select a delivery address."}, status=400)
        address = get_object_or_404(ShippingAddress, pk=address_id, user=request.user)
        try:
            order = services.create_order_from_cart(request.user, address)
        except services.CheckoutError as error:
            return _checkout_error(error)
        return Response({"success": True, "order": OrderSerializer(order).data}, status=status.HTTP_201_CREATED)


class OrderDetailAPIView(APIView):
    """GET /api/orders/<id>/ - only the owner can see an order (404 otherwise)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        order = get_object_or_404(Order.objects.prefetch_related('items__product', 'payments'), pk=pk, user=request.user)
        return Response(OrderSerializer(order).data)


class AddressListCreateAPIView(APIView):
    """GET/POST /api/addresses/ - the customer's own delivery addresses."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(AddressSerializer(ShippingAddress.objects.filter(user=request.user).order_by('-id'), many=True).data)

    def post(self, request):
        serializer = AddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AddressDetailAPIView(APIView):
    """GET/PUT/PATCH/DELETE /api/addresses/<id>/ - owner only (404 for anyone else)."""
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, request, pk):
        return get_object_or_404(ShippingAddress, pk=pk, user=request.user)

    def get(self, request, pk):
        return Response(AddressSerializer(self.get_object(request, pk)).data)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        serializer = AddressSerializer(self.get_object(request, pk), data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        # Past orders keep their own address snapshot, so deleting is safe.
        self.get_object(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentCreateAPIView(APIView):
    """POST /api/payments/create/ {"order_id"}

    Re-validates stock, creates the gateway order for the server-side order
    total and records a PENDING Payment. Returns what the Razorpay Checkout
    widget needs to open.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payments'

    def post(self, request):
        order = get_object_or_404(Order, pk=request.data.get('order_id') or 0, user=request.user)
        if order.status != Order.PENDING or order.payment_status:
            return Response({"success": False, "error": "This order is not awaiting payment."}, status=400)

        lines = [(i.product, i.quantity) for i in order.items.select_related('product')]
        problems = services.validate_stock(lines)
        if problems:
            return Response({"success": False, "error": "Some items can no longer be ordered.", "problems": problems}, status=409)

        amount_paise = int(order.total_price * 100)
        try:
            gateway_order_id = payments.create_gateway_order(
                amount_paise, receipt=f"order_{order.pk}", notes={'order_id': str(order.pk)},
            )
        except payments.PaymentGatewayNotConfigured:
            return Response({"success": False, "error": "Online payment is not available right now. Please try again later."}, status=503)
        except payments.PaymentGatewayError as error:
            return Response({"success": False, "error": str(error)}, status=502)

        Payment.objects.create(
            order=order, user=request.user, provider='razorpay',
            provider_order_id=gateway_order_id, amount=order.total_price, currency='INR',
        )
        address = order.delivery_address or {}
        return Response({
            "success": True,
            "order_id": order.pk,
            "key_id": settings.RAZORPAY_KEY_ID,
            "gateway_order_id": gateway_order_id,
            "amount": amount_paise,
            "currency": "INR",
            "prefill": {
                "name": address.get('full_name') or request.user.get_full_name(),
                "email": request.user.email,
                "contact": address.get('phone', ''),
            },
        }, status=status.HTTP_201_CREATED)


class PaymentVerifyAPIView(APIView):
    """POST /api/payments/verify/ {"razorpay_order_id", "razorpay_payment_id", "razorpay_signature"}

    The ONLY place an order becomes paid: the gateway signature is checked
    on the server before the payment is marked SUCCESS, the order CONFIRMED
    and stock deducted.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payments'

    def post(self, request):
        gateway_order_id = request.data.get('razorpay_order_id')
        gateway_payment_id = request.data.get('razorpay_payment_id')
        signature = request.data.get('razorpay_signature')
        payment = get_object_or_404(Payment, provider_order_id=gateway_order_id or '', user=request.user)

        if payment.status in (Payment.SUCCESS, Payment.REFUNDED):
            # Already applied (e.g. by the webhook or an earlier request): report, don't reprocess.
            return self._result(payment.order, services.ALREADY_PROCESSED, payment)

        if not payments.verify_signature(gateway_order_id, gateway_payment_id, signature):
            if payment.status == Payment.PENDING:
                payment.status = Payment.FAILED
                payment.failure_reason = 'Signature verification failed'
                payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
            logger.warning("payments/verify: invalid signature for payment id=%s", payment.pk)
            return Response({"success": False, "error": "Payment verification failed. The order has not been confirmed."}, status=400)

        order, outcome = services.confirm_paid_order(payment, gateway_payment_id)
        payment.refresh_from_db()
        return self._result(order, outcome, payment)

    def _result(self, order, outcome, payment):
        order.refresh_from_db()
        data = OrderSerializer(order).data
        if payment.refund_status != Payment.REFUND_NONE:
            return Response({
                "success": False,
                "error": "Payment received, but it could not be applied to this order. A refund will be issued.",
                "order": data,
            }, status=409)
        return Response({"success": order.status not in (Order.PENDING, Order.CANCELLED), "order": data})


class RazorpayWebhookAPIView(APIView):
    """POST /api/payments/webhook/ — Razorpay server-to-server events.

    Authenticated only by the X-Razorpay-Signature HMAC over the raw body
    (no session, so CSRF does not apply). Handles payment.captured /
    order.paid (confirm order + deduct stock), payment.failed and
    refund.processed. Redelivered events are ignored by event id and all
    processing is idempotent, so the order is confirmed and stock deducted
    once even if both the browser and the webhook report the payment.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_body = request.body  # must be read before request.data
        if not payments.verify_webhook_signature(raw_body, request.headers.get('X-Razorpay-Signature', '')):
            logger.warning("razorpay webhook: invalid or missing signature")
            return Response({"detail": "Invalid signature."}, status=400)
        try:
            payload = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "Invalid JSON."}, status=400)
        result = services.process_razorpay_webhook(request.headers.get('X-Razorpay-Event-Id', ''), payload)
        logger.info("razorpay webhook %s -> %s", payload.get('event'), result)
        return Response({"status": result})


class AddToCartAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get('product_id')
        try:
            quantity = int(request.data.get('quantity', 1))
        except (TypeError, ValueError):
            return Response({"error": "Quantity must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)

        if not product_id:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        if quantity < 1:
            return Response({"error": "Quantity must be at least 1."}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, id=product_id, is_active=True)

        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart_item = CartItem.objects.filter(cart=cart, product=product).first()
        new_quantity = quantity + (cart_item.quantity if cart_item else 0)
        # Stock is only checked here, never reserved - it's deducted after payment.
        if new_quantity > product.stock:
            return Response({"error": f"Only {product.stock} items available in stock."}, status=status.HTTP_400_BAD_REQUEST)

        if cart_item:
            cart_item.quantity = new_quantity
            cart_item.save()
        else:
            CartItem.objects.create(cart=cart, product=product, quantity=new_quantity)
        total_items = sum(item.quantity for item in cart.items.all())

        return Response({
            "message": f"Successfully added {product.name} to cart.",
            "cart_count": total_items
        }, status=status.HTTP_200_OK)


class UpdateCartItemAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        item_id = request.data.get('item_id')
        action = request.data.get('action')

        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)

        if action not in ('increase', 'decrease', 'remove'):
            return Response({"error": "Unknown cart action."}, status=status.HTTP_400_BAD_REQUEST)
        if action == 'increase' and not cart_item.product.is_active:
            return Response({"error": "This product is no longer available."}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'increase':
            if cart_item.product.stock > cart_item.quantity:
                cart_item.quantity += 1
                cart_item.save()
            else:
                return Response({"error": "Maximum stock limit reached"}, status=status.HTTP_400_BAD_REQUEST)
        elif action == 'decrease':
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
            else:
                cart_item.delete()
        elif action == 'remove':
            cart_item.delete()

        cart = Cart.objects.get(user=request.user)
        total_items = sum(item.quantity for item in cart.items.all())
        cart_total = cart.get_total()

        return Response({
            "message": "Cart updated successfully.",
            "cart_count": total_items,
            "cart_total": cart_total
        }, status=status.HTTP_200_OK)


class ToggleWishlistAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get('product_id')
        if not product_id:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, id=product_id)
        wishlist_item = Wishlist.objects.filter(user=request.user, product=product)

        if wishlist_item.exists():
            wishlist_item.delete()
            added = False
            message = "Removed from Wishlist"
        else:
            Wishlist.objects.create(user=request.user, product=product)
            added = True
            message = "Added to Wishlist"

        total_wishlist = Wishlist.objects.filter(user=request.user).count()

        return Response({
            "added": added,
            "message": message,
            "wishlist_count": total_wishlist
        }, status=status.HTTP_200_OK)


class CreateReviewAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ReviewSerializer(data=request.data)
        if serializer.is_valid():
            product = serializer.validated_data['product']
            if Review.objects.filter(product=product, user=request.user).exists():
                return Response({"error": "You have already reviewed this product."}, status=status.HTTP_400_BAD_REQUEST)
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SessionTokenObtainView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(request.user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })

    def post(self, request, *args, **kwargs):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(request.user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })

