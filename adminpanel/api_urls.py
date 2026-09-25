from django.urls import path

from . import api_views as v

urlpatterns = [
    path('dashboard/', v.DashboardAPIView.as_view(), name='api_admin_dashboard'),
    path('products/', v.ProductListCreateAPIView.as_view(), name='api_admin_products'),
    path('products/<int:pk>/', v.ProductDetailAPIView.as_view(), name='api_admin_product_detail'),
    path('products/<int:pk>/images/', v.ProductImageAPIView.as_view(), name='api_admin_product_images'),
    path('products/<int:pk>/images/<int:image_id>/', v.ProductImageAPIView.as_view(), name='api_admin_product_image_delete'),
    path('categories/', v.CategoryListCreateAPIView.as_view(), name='api_admin_categories'),
    path('categories/<int:pk>/', v.CategoryDetailAPIView.as_view(), name='api_admin_category_detail'),
    path('customers/', v.CustomerListAPIView.as_view(), name='api_admin_customers'),
    path('customers/<int:pk>/', v.CustomerDetailAPIView.as_view(), name='api_admin_customer_detail'),
    path('orders/', v.OrderListAPIView.as_view(), name='api_admin_orders'),
    path('orders/<int:pk>/', v.OrderDetailAPIView.as_view(), name='api_admin_order_detail'),
    path('orders/<int:pk>/status/', v.OrderStatusAPIView.as_view(), name='api_admin_order_status'),
    path('offers/', v.OfferListCreateAPIView.as_view(), name='api_admin_offers'),
    path('offers/<int:pk>/', v.OfferDetailAPIView.as_view(), name='api_admin_offer_detail'),
    path('payments/', v.PaymentListAPIView.as_view(), name='api_admin_payments'),
    path('reports/', v.ReportsAPIView.as_view(), name='api_admin_reports'),
]
