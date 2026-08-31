from .models import Cart, Wishlist
from .rbac import get_user_role, get_role_label, get_role_color


def cart_summary(request):
    """
    Injects the user's active cart and wishlist totals globally into templates.
    Also injects RBAC role information for role-aware UI rendering.
    """
    cart_items_count = 0
    wishlist_count = 0

    if request.user.is_authenticated:
        # Authenticated User
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_items_count = sum(item.quantity for item in cart.items.all())
        wishlist_count = Wishlist.objects.filter(user=request.user).count()
    else:
        # Handle anonymous cart via session
        session_cart = request.session.get('cart', {})
        cart_items_count = sum(item.get('quantity', 0) for item in session_cart.values())

    # ── RBAC role injection ──────────────────────────────────────────────────
    user = request.user
    user_role   = get_user_role(user)
    role_label  = get_role_label(user)
    role_color  = get_role_color(user)

    return {
        'global_cart_count':    cart_items_count,
        'global_wishlist_count': wishlist_count,
        # RBAC
        'user_role':   user_role,    # 'superadmin' | 'staff' | 'customer' | None
        'role_label':  role_label,   # Human-readable: 'Super Admin', etc.
        'role_color':  role_color,   # CSS colour token for badges
    }

