"""Admin panel pages. Each page is a shell; all data is loaded from and
saved to the /api/admin/ endpoints."""
from django.views.generic import TemplateView

from shop.models import Order
from shop.rbac import ADMIN_ROLES, RBACMixin


class AdminPageView(RBACMixin, TemplateView):
    allowed_roles = list(ADMIN_ROLES)
    login_url = 'admin_login'
    rbac_redirect_url = 'home'
    active_nav = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = self.active_nav
        context['order_statuses'] = Order.STATUS_CHOICES
        return context


class DashboardPage(AdminPageView):
    template_name = 'adminpanel/dashboard.html'
    active_nav = 'dashboard'


class ProductsPage(AdminPageView):
    template_name = 'adminpanel/products.html'
    active_nav = 'products'


class ProductFormPage(AdminPageView):
    template_name = 'adminpanel/product_form.html'
    active_nav = 'products'


class CategoriesPage(AdminPageView):
    template_name = 'adminpanel/categories.html'
    active_nav = 'categories'


class CustomersPage(AdminPageView):
    template_name = 'adminpanel/customers.html'
    active_nav = 'customers'


class OrdersPage(AdminPageView):
    template_name = 'adminpanel/orders.html'
    active_nav = 'orders'


class OrderDetailPage(AdminPageView):
    template_name = 'adminpanel/order_detail.html'
    active_nav = 'orders'


class InventoryPage(AdminPageView):
    template_name = 'adminpanel/inventory.html'
    active_nav = 'inventory'


class NewLaunchesPage(AdminPageView):
    template_name = 'adminpanel/new_launches.html'
    active_nav = 'new_launches'


class OffersPage(AdminPageView):
    template_name = 'adminpanel/offers.html'
    active_nav = 'offers'


class PaymentsPage(AdminPageView):
    template_name = 'adminpanel/payments.html'
    active_nav = 'payments'


class ReportsPage(AdminPageView):
    template_name = 'adminpanel/reports.html'
    active_nav = 'reports'


class ProfilePage(AdminPageView):
    template_name = 'adminpanel/profile.html'
    active_nav = 'profile'
