import uuid
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django.contrib.auth import login, authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .forms import UserRegisterForm

from .models import (
    Category, Product, Cart, CartItem, Wishlist,
    Order, OrderItem, ShippingAddress, Review, Conversation, Message, HomeBanner
)

@csrf_exempt
def ajax_login_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            password = data.get('password')
            
            if not email or '@' not in email:
                return JsonResponse({
                    'success': False,
                    'error': 'Please enter a valid email address.'
                }, status=400)
            
            username = None
            try:
                user_obj = User.objects.get(email__iexact=email)
                username = user_obj.username
            except User.DoesNotExist:
                pass
            
            # Authenticate user using the translated username
            user = None
            if username:
                user = authenticate(request, username=username, password=password)
            
            if user is not None:
                auth_login(request, user)
                
                # Session strictly expires when the browser closes (mandatory login every time)
                request.session.set_expiry(0)
                
                redirect_url = None
                if user.is_staff or user.is_superuser:
                    redirect_url = '/admin-dashboard/'
                    
                return JsonResponse({
                    'success': True, 
                    'message': 'Login successful. Forwarding...',
                    'redirect_url': redirect_url
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': 'Access denied. Check credentials and try again.'
                }, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid transaction request.'}, status=400)
            
    return JsonResponse({'success': False, 'error': 'Method unavailable.'}, status=405)


def admin_login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect('admin_dashboard')
        return redirect('home')
    return render(request, 'registration/admin_login.html')


@csrf_exempt
def ajax_admin_login_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            password = data.get('password')
            
            if not email or '@' not in email:
                return JsonResponse({
                    'success': False,
                    'error': 'Please enter a valid email address.'
                }, status=400)
            
            username = None
            try:
                user_obj = User.objects.get(email__iexact=email)
                username = user_obj.username
            except User.DoesNotExist:
                pass
            
            user = None
            if username:
                user = authenticate(request, username=username, password=password)
            
            if user is not None:
                if not (user.is_staff or user.is_superuser):
                    return JsonResponse({
                        'success': False,
                        'error': 'Access denied. This portal is restricted to Developers and Administrators.'
                    }, status=403)
                
                auth_login(request, user)
                request.session.set_expiry(0)
                
                return JsonResponse({
                    'success': True,
                    'message': 'Developer Authentication Successful. Connecting to Dashboard...',
                    'redirect_url': '/admin-dashboard/'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid Developer credentials. Access Denied.'
                }, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid request structure.'}, status=400)
            
    return JsonResponse({'success': False, 'error': 'Method unavailable.'}, status=405)


def register_view(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, "Welcome to Shopping_App! Your account has been successfully created.")
            return redirect('home')
    else:
        form = UserRegisterForm()
    return render(request, 'registration/register.html', {'form': form})



# ----------------- CATALOG VIEWS ----------------- #

class HomeView(LoginRequiredMixin, View):
    def get(self, request):
        featured_products = Product.objects.filter(featured=True, is_active=True)[:4]
        latest_products = Product.objects.filter(is_active=True).order_by('-created_at')[:8]
        categories = Category.objects.all()[:6]
        banners = HomeBanner.objects.filter(is_active=True)
        highlight_products = Product.objects.filter(
            Q(is_highlight=True) | Q(discount_price__isnull=False),
            is_active=True
        ).distinct().order_by('-created_at')
        
        context = {
            'featured_products': featured_products,
            'latest_products': latest_products,
            'categories': categories,
            'banner': banners.first() if banners.exists() else None,
            'highlight_products': highlight_products
        }
        return render(request, 'shop/home.html', context)


class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = 'shop/product_list.html'
    context_object_name = 'products'
    paginate_by = 12

    def get_queryset(self):
        queryset = Product.objects.filter(is_active=True)
        
        # Category Filtering
        category_slug = self.request.GET.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
            
        # Search Filtering
        query = self.request.GET.get('q')
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | 
                Q(description__icontains=query)
            )
            
        # Price Range Filtering
        min_price = self.request.GET.get('min_price')
        max_price = self.request.GET.get('max_price')
        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)
            
        # Ordering
        sort = self.request.GET.get('sort')
        if sort == 'price_low':
            queryset = queryset.order_by('price')
        elif sort == 'price_high':
            queryset = queryset.order_by('-price')
        elif sort == 'newest':
            queryset = queryset.order_by('-created_at')
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        # Pass wishlist product IDs for active hearts in list view
        if self.request.user.is_authenticated:
            context['wishlisted_ids'] = Wishlist.objects.filter(user=self.request.user).values_list('product_id', flat=True)
        else:
            context['wishlisted_ids'] = []
        return context


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = 'shop/product_detail.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reviews'] = self.object.reviews.all().order_by('-created_at')
        context['related_products'] = Product.objects.filter(
            category=self.object.category, is_active=True
        ).exclude(id=self.object.id)[:4]
        
        if self.request.user.is_authenticated:
            context['is_in_wishlist'] = Wishlist.objects.filter(user=self.request.user, product=self.object).exists()
        else:
            context['is_in_wishlist'] = False
            
        return context


# ----------------- CART & WISHLIST ----------------- #

class CartDetailView(LoginRequiredMixin, View):
    def get(self, request):
        cart, created = Cart.objects.get_or_create(user=request.user)
        return render(request, 'shop/cart.html', {'cart': cart})


class WishlistListView(LoginRequiredMixin, ListView):
    model = Wishlist
    template_name = 'shop/wishlist.html'
    context_object_name = 'wishlist_items'

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user)


# ----------------- CHECKOUT & ORDERS ----------------- #

class ShippingAddressListView(LoginRequiredMixin, ListView):
    model = ShippingAddress
    template_name = 'shop/addresses.html'
    context_object_name = 'addresses'

    def get_queryset(self):
        return ShippingAddress.objects.filter(user=self.request.user)


class ShippingAddressCreateView(LoginRequiredMixin, CreateView):
    model = ShippingAddress
    template_name = 'shop/address_form.html'
    fields = ['full_name', 'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'phone']
    success_url = '/checkout/'

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


class CheckoutView(LoginRequiredMixin, View):
    def get(self, request):
        cart, created = Cart.objects.get_or_create(user=request.user)
        if not cart.items.exists():
            messages.warning(request, "Your cart is empty!")
            return redirect('product_list')
            
        addresses = ShippingAddress.objects.filter(user=request.user)
        return render(request, 'shop/checkout.html', {'cart': cart, 'addresses': addresses})

    @csrf_exempt
    def post(self, request):
        cart = get_object_or_404(Cart, user=request.user)
        if not cart.items.exists():
            return JsonResponse({'success': False, 'error': 'Your cart is empty!'}, status=400)
            
        # Parse JSON or fallback to standard form data
        try:
            data = json.loads(request.body)
            address_id = data.get('address_id')
        except Exception:
            address_id = request.POST.get('address_id')
            
        if not address_id:
            return JsonResponse({'success': False, 'error': 'Please select a shipping address.'}, status=400)
            
        address = get_object_or_404(ShippingAddress, id=address_id, user=request.user)
        
        # 1. Create the Order in database as Pending
        order = Order.objects.create(
            user=request.user,
            shipping_address=address,
            total_price=cart.get_total(),
            payment_status=False,
            status='Pending'
        )
        
        # 2. Map items to OrderItem to lock historical price and quantity
        for item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                product_name=item.product.name,
                price=item.product.final_price,
                quantity=item.quantity
            )
            
        # 3. Create Razorpay Order or trigger Sandbox Mode
        from django.conf import settings
        
        is_sandbox = (not settings.RAZORPAY_KEY_ID or 
                      not settings.RAZORPAY_KEY_SECRET or 
                      settings.RAZORPAY_KEY_ID == 'rzp_test_5Nn1fNn1DUMMYKEY' or 
                      settings.RAZORPAY_KEY_SECRET == 'DUMMYSECRETKEY1234567890' or
                      settings.RAZORPAY_KEY_ID == 'rzp_test_DUMMY_KEY_ID' or
                      settings.RAZORPAY_KEY_SECRET == 'DUMMY_KEY_SECRET')
        
        if is_sandbox:
            # Under Sandbox mode, we generate a mock Razorpay Order ID and skip calling Razorpay's servers!
            mock_order_id = f"order_mock_{uuid.uuid4().hex[:12]}"
            order.razorpay_order_id = mock_order_id
            order.save()
            
            return JsonResponse({
                'success': True,
                'sandbox_mode': True,
                'razorpay_order_id': mock_order_id,
                'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                'amount': int(order.total_price * 100),
                'currency': 'INR',
                'order_id': order.id,
                'customer_name': address.full_name or request.user.get_full_name() or request.user.username,
                'customer_email': request.user.email or "customer@example.com",
                'customer_phone': address.phone or "9999999999"
            })
            
        import razorpay
        try:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            amount_in_paise = int(order.total_price * 100)
            
            razorpay_order = client.order.create({
                'amount': 100000000,
                'currency': 'INR',
                'payment_capture': '1'
            })
            
            # Save the Razorpay Order ID to our Order model
            order.razorpay_order_id = razorpay_order['id']
            order.save()
            
            return JsonResponse({
                'success': True,
                'sandbox_mode': False,
                'razorpay_order_id': razorpay_order['id'],
                'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                'amount': 100000000,
                'currency': 'INR',
                'order_id': order.id,
                'customer_name': address.full_name or request.user.get_full_name() or request.user.username,
                'customer_email': request.user.email or "customer@example.com",
                'customer_phone': address.phone or "9999999999"
            })
            
        except Exception as e:
            # Clean up the pending order on failure
            order.delete()
            return JsonResponse({
                'success': False,
                'error': f'Razorpay transaction initiation failed: {str(e)}'
            }, status=500)


@csrf_exempt
def verify_payment_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            razorpay_order_id = data.get('razorpay_order_id')
            razorpay_payment_id = data.get('razorpay_payment_id')
            razorpay_signature = data.get('razorpay_signature')
            order_id = data.get('order_id')
            
            if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature, order_id]):
                return JsonResponse({'success': False, 'error': 'Missing payment verification credentials.'}, status=400)
                
            order = get_object_or_404(Order, id=order_id, user=request.user)
            
            # Check Sandbox Mode bypass
            from django.conf import settings
            is_sandbox = (not settings.RAZORPAY_KEY_ID or 
                          not settings.RAZORPAY_KEY_SECRET or 
                          settings.RAZORPAY_KEY_ID == 'rzp_test_5Nn1fNn1DUMMYKEY' or 
                          settings.RAZORPAY_KEY_SECRET == 'DUMMYSECRETKEY1234567890' or
                          settings.RAZORPAY_KEY_ID == 'rzp_test_DUMMY_KEY_ID' or
                          settings.RAZORPAY_KEY_SECRET == 'DUMMY_KEY_SECRET')
            
            if is_sandbox and razorpay_order_id.startswith('order_mock_'):
                # In sandbox mode, bypass cryptographic signature verify
                pass
            else:
                # Verify Signature using Razorpay SDK
                import razorpay
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                try:
                    client.utility.verify_payment_signature({
                        'razorpay_order_id': razorpay_order_id,
                        'razorpay_payment_id': razorpay_payment_id,
                        'razorpay_signature': razorpay_signature
                    })
                except Exception:
                    return JsonResponse({'success': False, 'error': 'Security verification check failed. Payment rejected.'}, status=400)
                
            # Update order payment state to successful
            order.payment_id = razorpay_payment_id
            order.payment_status = True
            order.status = 'Processing'
            order.tracking_number = f"TRK{uuid.uuid4().hex[:10].upper()}"
            order.save()
            
            # Reduce inventory stock
            for item in order.items.all():
                product = item.product
                if product and product.stock >= item.quantity:
                    product.stock -= item.quantity
                    product.save()
                    
            # Clear user cart items
            cart, created = Cart.objects.get_or_create(user=request.user)
            cart.items.all().delete()
            
            messages.success(request, f"Success! Your order #{order.id} has been placed. Reference ID: {order.tracking_number}")
            
            return JsonResponse({
                'success': True,
                'redirect_url': f"/orders/{order.id}/"
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Verification error: {str(e)}'}, status=500)
            
    return JsonResponse({'success': False, 'error': 'Method unavailable.'}, status=405)



# ----------------------- CHAT -----------------------

class ConversationListView(LoginRequiredMixin, ListView):
    """List all conversations for the logged-in user."""
    model = Conversation
    template_name = 'shop/conversations_list.html'
    context_object_name = 'conversations'
    paginate_by = 20

    def get_queryset(self):
        """Get conversations where user is either customer or seller."""
        user = self.request.user
        return Conversation.objects.filter(
            Q(customer=user) | Q(seller=user)
        ).prefetch_related('messages')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['unread_count'] = Message.objects.filter(
            conversation__in=self.get_queryset(),
            is_read=False
        ).exclude(sender=self.request.user).count()
        return context


class ConversationDetailView(LoginRequiredMixin, DetailView):
    """Display a specific conversation and chat thread."""
    model = Conversation
    template_name = 'shop/chat.html'
    context_object_name = 'conversation'

    def get_object(self, queryset=None):
        """Verify user is part of the conversation."""
        obj = super().get_object(queryset)
        if self.request.user != obj.customer and self.request.user != obj.seller:
            raise PermissionError("You don't have access to this conversation.")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversation = self.object
        
        # Mark messages as read
        Message.objects.filter(
            conversation=conversation,
            is_read=False
        ).exclude(sender=self.request.user).update(is_read=True)
        
        # Get other user in conversation
        if self.request.user == conversation.customer:
            context['other_user'] = conversation.seller
        else:
            context['other_user'] = conversation.customer
            
        return context


class StartConversationView(LoginRequiredMixin, View):
    """Start a new conversation with a seller about a product."""
    
    def post(self, request):
        seller_id = request.POST.get('seller_id')
        product_id = request.POST.get('product_id')
        
        if not seller_id or not product_id:
            return JsonResponse({'error': 'Missing seller or product'}, status=400)
        
        seller = get_object_or_404(User, id=seller_id)
        product = get_object_or_404(Product, id=product_id)
        
        # Prevent self-conversation
        if seller == request.user:
            return JsonResponse({'error': 'Cannot chat with yourself'}, status=400)
        
        # Get or create conversation
        conversation, created = Conversation.objects.get_or_create(
            customer=request.user,
            seller=seller,
            product=product,
            defaults={'updated_at': timezone.now()}
        )
        
        return JsonResponse({
            'success': True,
            'conversation_id': conversation.id,
            'redirect_url': f'/chat/{conversation.id}/'
        })


class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = 'shop/orders_list.html'
    context_object_name = 'orders'

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related('items__product').order_by('-created_at')


class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'shop/order_detail.html'
    context_object_name = 'order'

    def get_queryset(self):
        # Ensure users only view their own orders
        return Order.objects.filter(user=self.request.user)


class AdminDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        # Restrict access to staff and superusers only
        if not request.user.is_staff:
            messages.error(request, "You do not have permission to access the admin dashboard.")
            return redirect('home')
        
        context = {
            'total_orders': Order.objects.count(),
            'total_products': Product.objects.count(),
            'total_users': User.objects.count(),
            'recent_orders': Order.objects.prefetch_related('items').order_by('-created_at')[:5],
        }
        return render(request, 'shop/admin_dashboard.html', context)


class UserDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        orders_count = Order.objects.filter(user=user).count()
        wishlist_count = Wishlist.objects.filter(user=user).count()
        chat_count = Conversation.objects.filter(Q(customer=user) | Q(seller=user)).count()
        addresses_count = ShippingAddress.objects.filter(user=user).count()
        
        recent_orders = Order.objects.filter(user=user).prefetch_related('items').order_by('-created_at')[:5]
        
        context = {
            'orders_count': orders_count,
            'wishlist_count': wishlist_count,
            'chat_count': chat_count,
            'addresses_count': addresses_count,
            'recent_orders': recent_orders,
        }
        return render(request, 'shop/dashboard.html', context)


@csrf_exempt
def custom_logout_view(request):
    auth_logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('login')



