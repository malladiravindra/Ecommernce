import uuid
import json
import random
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django.contrib.auth import login, authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from .forms import UserRegisterForm
from .rbac import RBACMixin, get_user_role, role_required, user_summary
from . import services
from .offers import active_offers, attach_offers
from rest_framework_simplejwt.tokens import RefreshToken


from .models import (
    Category, Product, Cart, CartItem, Wishlist,
    Order, OrderItem, ShippingAddress, Review, Conversation, Message, HomeBanner
)

@login_not_required
@ensure_csrf_cookie
def login_view(request):
    """Render the unified authentication page (login + registration)."""
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect('adminpanel:dashboard')
        return redirect('home')
    return render(request, 'registration/login.html', {'default_mode': 'login'})


LOGIN_ATTEMPT_LIMIT = 10          # attempts
LOGIN_ATTEMPT_WINDOW = 5 * 60     # seconds, per client IP


def _login_rate_limited(request, scope):
    """Simple per-IP limiter for the session login endpoints (cache backed)."""
    from rest_framework.throttling import BaseThrottle
    # Same client-IP logic as DRF throttling (honours REST_FRAMEWORK NUM_PROXIES),
    # so a spoofed X-Forwarded-For can't be used to dodge the limit.
    ip = BaseThrottle().get_ident(request)
    key = f"login-attempts:{scope}:{ip}"
    cache.add(key, 0, LOGIN_ATTEMPT_WINDOW)
    try:
        attempts = cache.incr(key)
    except ValueError:  # key expired between add() and incr()
        cache.set(key, 1, LOGIN_ATTEMPT_WINDOW)
        attempts = 1
    return attempts > LOGIN_ATTEMPT_LIMIT


def ajax_login_view(request):
    """Session login used by the customer login page (CSRF-protected)."""
    if request.method == 'POST':
        if _login_rate_limited(request, 'customer'):
            return JsonResponse({'success': False, 'error': 'Too many login attempts. Please wait a few minutes and try again.'}, status=429)
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
                    redirect_url = '/panel/'
                
                refresh = RefreshToken.for_user(user)
                return JsonResponse({
                    'success': True, 
                    'message': 'Login successful. Forwarding...',
                    'redirect_url': redirect_url,
                    'user': user_summary(user),
                    'access_token': str(refresh.access_token),
                    'refresh_token': str(refresh)
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': 'Access denied. Check credentials and try again.'
                }, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid transaction request.'}, status=400)
            
    return JsonResponse({'success': False, 'error': 'Method unavailable.'}, status=405)


@ensure_csrf_cookie
def admin_login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect('adminpanel:dashboard')
        return redirect('home')
    return render(request, 'registration/admin_login.html')


def ajax_admin_login_view(request):
    """Session login used by the admin login page (CSRF-protected)."""
    if request.method == 'POST':
        if _login_rate_limited(request, 'admin'):
            return JsonResponse({'success': False, 'error': 'Too many login attempts. Please wait a few minutes and try again.'}, status=429)
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
                
                refresh = RefreshToken.for_user(user)
                return JsonResponse({
                    'success': True,
                    'message': 'Developer Authentication Successful. Connecting to Dashboard...',
                    'redirect_url': '/panel/',
                    'user': user_summary(user),
                    'access_token': str(refresh.access_token),
                    'refresh_token': str(refresh)
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid Developer credentials. Access Denied.'
                }, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid request structure.'}, status=400)
            
    return JsonResponse({'success': False, 'error': 'Method unavailable.'}, status=405)


@ensure_csrf_cookie
def register_view(request):
    """Render the unified authentication page in Registration mode.

    The form submits to /api/accounts/register/ (email-OTP verification);
    this view never creates accounts itself.
    """
    if request.user.is_authenticated:
        return redirect('home')
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)
    return render(request, 'registration/login.html', {
        'form': UserRegisterForm(),
        'default_mode': 'register',
    })


# ----------------- OTP PASSWORD RESET FLOW ----------------- #

def forgot_password_view(request):
    """Step 1: Render forgot password page."""
    if request.method == 'GET':
        if not request.user.is_authenticated:
            return render(request, 'registration/forgot_password.html')
        return redirect('home')
    return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)


def verify_otp_view(request):
    """Step 2: Render OTP verification page."""
    if request.method == 'GET':
        return render(request, 'registration/verify_otp.html')
    return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)


def reset_password_view(request):
    """Step 3: Render reset password page."""
    if request.method == 'GET':
        return render(request, 'registration/reset_password.html')
    return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)




class HomeView(LoginRequiredMixin, View):
    def get(self, request):
        featured_products = Product.objects.filter(featured=True, is_active=True)[:4]
        latest_products = Product.objects.filter(is_active=True).order_by('-created_at')[:8]
        categories = Category.objects.all()[:6]
        banners = HomeBanner.objects.filter(is_active=True)
        offers = active_offers()
        offer_ids = [o.pk for o in offers]
        highlight_products = Product.objects.filter(
            Q(is_highlight=True) | Q(discount_price__isnull=False) | Q(offers__in=offer_ids) | Q(category__offers__in=offer_ids),
            is_active=True
        ).distinct().order_by('-created_at')

        context = {
            'featured_products': attach_offers(list(featured_products), offers),
            'latest_products': attach_offers(list(latest_products), offers),
            'new_launch_products': attach_offers(
                list(Product.objects.filter(is_active=True, is_new_launch=True).order_by('-created_at')[:8]), offers),
            'categories': categories,
            'banner': banners.first() if banners.exists() else None,
            'highlight_products': attach_offers(list(highlight_products), offers),
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
            
        # New launches only (admin-controlled flag)
        if self.request.GET.get('new') == '1':
            queryset = queryset.filter(is_new_launch=True)

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
        else:
            queryset = queryset.order_by('-created_at', 'pk')

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        # One offer lookup for the whole page instead of one per product.
        context['products'] = attach_offers(list(context['products']))
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

    def get_queryset(self):
        # Inactive products are hidden from customers everywhere, including by direct URL.
        return Product.objects.filter(is_active=True).select_related('category').prefetch_related('images')

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


class ShippingAddressFormView(LoginRequiredMixin, View):
    """Add/edit address page. The form saves through /api/addresses/."""
    def get(self, request, pk=None):
        from django.utils.http import url_has_allowed_host_and_scheme
        if pk is not None:
            get_object_or_404(ShippingAddress, pk=pk, user=request.user)
        next_url = request.GET.get('next', '')
        if not (next_url.startswith('/') and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})):
            next_url = ''
        return render(request, 'shop/address_form.html', {
            'address_id': pk,
            'next_url': next_url,
        })


class CheckoutView(LoginRequiredMixin, View):
    """Checkout page. Order creation and payment happen through
    /api/orders/, /api/payments/create/ and /api/payments/verify/."""
    def get(self, request):
        cart, items, totals = services.cart_summary(request.user)
        if not items:
            messages.warning(request, "Your cart is empty!")
            return redirect('product_list')
        addresses = ShippingAddress.objects.filter(user=request.user).order_by('-id')
        return render(request, 'shop/checkout.html', {
            'cart': cart,
            'items': items,
            'totals': totals,
            'addresses': addresses,
            'stock_problems': services.validate_stock((i.product, i.quantity) for i in items),
        })



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
        return Order.objects.filter(user=self.request.user).prefetch_related('items__product', 'payments')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        icons = {
            Order.CONFIRMED: 'fa-file-invoice-dollar', Order.PROCESSING: 'fa-box-open',
            Order.SHIPPED: 'fa-truck-fast', Order.OUT_FOR_DELIVERY: 'fa-motorcycle',
            Order.DELIVERED: 'fa-handshake-simple',
        }
        labels = dict(Order.STATUS_CHOICES)
        context['tracking_steps'] = [(code, labels[code], icons[code]) for code in Order.TRACKING_STEPS]
        return context


class OrderConfirmationView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'shop/order_confirmation.html'
    context_object_name = 'order'

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related('items__product', 'payments')


class ProfilePageView(LoginRequiredMixin, View):
    """Profile page. Reads/writes through /api/accounts/profile/."""
    def get(self, request):
        return render(request, 'shop/profile.html')


class AdminDashboardView(RBACMixin, View):
    """Legacy URL — the admin dashboard now lives in the separate admin panel."""
    allowed_roles = ['staff', 'superadmin']
    rbac_redirect_url = 'home'

    def get(self, request):
        return redirect('adminpanel:dashboard')


class UserDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        orders_count    = Order.objects.filter(user=user).count()
        wishlist_count  = Wishlist.objects.filter(user=user).count()
        chat_count      = Conversation.objects.filter(Q(customer=user) | Q(seller=user)).count()
        addresses_count = ShippingAddress.objects.filter(user=user).count()

        # Cart item count
        cart_count = 0
        try:
            cart_obj = Cart.objects.get(user=user)
            cart_count = cart_obj.items.count()
        except Cart.DoesNotExist:
            pass

        recent_orders = Order.objects.filter(user=user).prefetch_related('items').order_by('-created_at')[:5]

        context = {
            'orders_count':    orders_count,
            'wishlist_count':  wishlist_count,
            'chat_count':      chat_count,
            'addresses_count': addresses_count,
            'cart_count':      cart_count,
            'recent_orders':   recent_orders,
        }
        return render(request, 'shop/dashboard.html', context)


@require_POST
def custom_logout_view(request):
    auth_logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('login')



