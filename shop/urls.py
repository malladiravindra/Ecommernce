from django.urls import path
from django.contrib.auth import views as auth_views
from . import views, api_views

urlpatterns = [
    # Static & Catalog
    path('', views.HomeView.as_view(), name='home'),
    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('products/<slug:slug>/', views.ProductDetailView.as_view(), name='product_detail'),

    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('ajax-login/', views.ajax_login_view, name='api_login'),
    path('logout/', views.custom_logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('dashboard/', views.UserDashboardView.as_view(), name='user_dashboard'),
    
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='registration/password_reset_form.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),

    # Cart & Wishlist UI
    path('cart/', views.CartDetailView.as_view(), name='cart_detail'),
    path('wishlist/', views.WishlistListView.as_view(), name='wishlist'),

    # Checkout & Addresses UI
    path('addresses/', views.ShippingAddressListView.as_view(), name='shipping_address_list'),
    path('addresses/add/', views.ShippingAddressCreateView.as_view(), name='shipping_address_add'),
    path('checkout/', views.CheckoutView.as_view(), name='checkout'),
    path('checkout/verify/', views.verify_payment_view, name='checkout_verify'),
    
    # Orders UI
    path('orders/', views.OrderListView.as_view(), name='order_list'),
    path('orders/<int:pk>/', views.OrderDetailView.as_view(), name='order_detail'),
    
    # Admin Custom Dashboard
    path('admin-dashboard/', views.AdminDashboardView.as_view(), name='admin_dashboard'),

    # Chat/Messaging
    path('chat/', views.ConversationListView.as_view(), name='conversation_list'),
    path('chat/<int:pk>/', views.ConversationDetailView.as_view(), name='conversation_detail'),
    path('chat/start/', views.StartConversationView.as_view(), name='start_conversation'),

    path('api/cart/add/', api_views.AddToCartAPI.as_view(), name='api_cart_add'),
    path('api/cart/update/', api_views.UpdateCartItemAPI.as_view(), name='api_cart_update'),
    path('api/wishlist/toggle/', api_views.ToggleWishlistAPI.as_view(), name='api_wishlist_toggle'),
    path('api/reviews/create/', api_views.CreateReviewAPI.as_view(), name='api_review_create'),
]
