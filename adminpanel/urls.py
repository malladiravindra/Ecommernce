from django.urls import path

from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.DashboardPage.as_view(), name='dashboard'),
    path('products/', views.ProductsPage.as_view(), name='products'),
    path('products/add/', views.ProductFormPage.as_view(), name='product_add'),
    path('products/<int:pk>/edit/', views.ProductFormPage.as_view(), name='product_edit'),
    path('categories/', views.CategoriesPage.as_view(), name='categories'),
    path('customers/', views.CustomersPage.as_view(), name='customers'),
    path('orders/', views.OrdersPage.as_view(), name='orders'),
    path('orders/<int:pk>/', views.OrderDetailPage.as_view(), name='order_detail'),
    path('inventory/', views.InventoryPage.as_view(), name='inventory'),
    path('new-launches/', views.NewLaunchesPage.as_view(), name='new_launches'),
    path('offers/', views.OffersPage.as_view(), name='offers'),
    path('payments/', views.PaymentsPage.as_view(), name='payments'),
    path('reports/', views.ReportsPage.as_view(), name='reports'),
    path('profile/', views.ProfilePage.as_view(), name='profile'),
]
