"""
shop/rbac.py — Role-Based Access Control helpers for the e-commerce project.

Roles (derived from Django's built-in User flags — no extra model needed):
    superadmin  →  user.is_superuser = True
    staff       →  user.is_staff = True  AND  user.is_superuser = False
    customer    →  regular authenticated user

Usage
-----
Decorator (function-based views):
    @role_required('superadmin', 'staff')
    def my_view(request): ...

Mixin (class-based views):
    class MyView(RBACMixin, View):
        allowed_roles = ['superadmin']
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.permissions import BasePermission

# Roles that make up the ADMIN side of the shop. Everyone else who is
# logged in is a CUSTOMER.
ADMIN_ROLES = ('superadmin', 'staff')


# ─────────────────────────────────────────────────────────────
# Role resolution
# ─────────────────────────────────────────────────────────────

def get_user_role(user):
    """Return the canonical role string for *user*.

    Returns one of: 'superadmin', 'staff', 'customer', or None (anonymous).
    """
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'superadmin'
    if user.is_staff:
        return 'staff'
    return 'customer'


def get_role_label(user):
    """Human-readable label for the user's role (used in UI badges)."""
    role = get_user_role(user)
    return {
        'superadmin': 'Super Admin',
        'staff':      'Staff / Manager',
        'customer':   'Customer',
    }.get(role, 'Guest')


def get_role_color(user):
    """Bootstrap-compatible colour token for the role badge."""
    role = get_user_role(user)
    return {
        'superadmin': '#ef4444',   # red
        'staff':      '#f59e0b',   # amber
        'customer':   '#10b981',   # emerald
    }.get(role, '#6b7280')


# ─────────────────────────────────────────────────────────────
# Decorator for function-based views
# ─────────────────────────────────────────────────────────────

def role_required(*roles, redirect_url=None):
    """Decorator that restricts a view to users whose role is in *roles*.

    Unauthenticated users are sent to the login page.
    Authenticated users without the required role see an error and are
    redirected to *redirect_url* (defaults to 'home').
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            role = get_user_role(request.user)
            if role not in roles:
                messages.error(request, "You do not have permission to access this page.")
                return redirect(redirect_url or 'home')
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


# ─────────────────────────────────────────────────────────────
# Mixin for class-based views
# ─────────────────────────────────────────────────────────────

class RBACMixin(LoginRequiredMixin):
    """CBV mixin that enforces role-based access.

    Set `allowed_roles` on the view class to a list of role strings.
    Inherits LoginRequiredMixin so unauthenticated users hit login first.

    Example::
        class AdminView(RBACMixin, View):
            allowed_roles = ['superadmin', 'staff']
    """
    allowed_roles = []          # subclasses must override
    rbac_redirect_url = 'home'  # where to send unauthorised users

    def dispatch(self, request, *args, **kwargs):
        # The role must be checked BEFORE the view runs — otherwise the
        # handler (e.g. a POST that changes data) executes for any
        # logged-in user and only its response gets replaced.
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        role = get_user_role(request.user)
        if self.allowed_roles and role not in self.allowed_roles:
            messages.error(request, "You do not have permission to access this page.")
            return redirect(self.rbac_redirect_url)
        return super().dispatch(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────────
# DRF permission for APIViews
# ─────────────────────────────────────────────────────────────

class HasRole(BasePermission):
    """DRF permission that restricts an APIView to `allowed_roles`.

    Example::
        class StaffOnlyAPI(APIView):
            permission_classes = [HasRole]
            allowed_roles = ['superadmin', 'staff']
    """
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        return get_user_role(request.user) in getattr(view, 'allowed_roles', [])


class IsAdminRole(BasePermission):
    """DRF permission: ADMIN side only (staff or super admin)."""
    message = "Admin access required."

    def has_permission(self, request, view):
        return get_user_role(request.user) in ADMIN_ROLES


def is_admin_user(user):
    return get_user_role(user) in ADMIN_ROLES


def get_account_type(user):
    """Application-level role used by the UI: ('admin', 'Administrator') for
    staff/super admins, ('customer', 'Customer') for everyone else logged in.
    Always derived from the user record on the server, never from the client."""
    if not user or not user.is_authenticated:
        return None, None
    if is_admin_user(user):
        return 'admin', 'Administrator'
    return 'customer', 'Customer'


def user_summary(user):
    """Safe, non-sensitive description of the signed-in user for API responses."""
    role, account_type = get_account_type(user)
    return {
        'id': user.pk,
        'name': user.get_full_name() or user.username,
        'email': user.email,
        'role': role,
        'account_type': account_type,
    }
