from .models import Cart, Wishlist

def cart_summary(request):
    """
    Injects the user's active cart and wishlist totals globally into templates.
    """
    cart_items_count = 0
    wishlist_count = 0
    
    if request.user.is_authenticated:
        # Authenticated User
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_items_count = sum(item.quantity for item in cart.items.all())
        wishlist_count = Wishlist.objects.filter(user=request.user).count()
    else:
        # Optional: Handle anonymous cart logic via session keys if desired, 
        # but we'll default to 0 for simplicity or you could implement session carts here.
        session_cart = request.session.get('cart', {})
        cart_items_count = sum(item.get('quantity', 0) for item in session_cart.values())
        
    return {
        'global_cart_count': cart_items_count,
        'global_wishlist_count': wishlist_count,
    }
