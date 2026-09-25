from django.contrib import admin
from .models import (
    Category, Product, ProductImage, Cart, CartItem, 
    Wishlist, ShippingAddress, Order, OrderItem, Payment, Review, Offer,
    Conversation, Message, HomeBanner
)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'discount_price', 'stock', 'is_active', 'featured', 'is_highlight', 'is_new_launch', 'created_at')
    list_filter = ('is_active', 'featured', 'is_highlight', 'is_new_launch', 'category', 'created_at')
    list_editable = ('price', 'discount_price', 'stock', 'is_active', 'featured', 'is_highlight', 'is_new_launch')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'description')
    inlines = [ProductImageInline]


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'get_items_count')
    inlines = [CartItemInline]

    def get_items_count(self, obj):
        return obj.items.count()
    get_items_count.short_description = 'Number of Items'


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('user__username', 'product__name')


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'city', 'state', 'postal_code')
    search_fields = ('user__username', 'full_name', 'city', 'postal_code')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'product_name', 'price', 'quantity', 'get_subtotal')


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    readonly_fields = ('provider', 'provider_order_id', 'provider_payment_id', 'amount', 'currency', 'status', 'failure_reason', 'created_at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Status changes go through the admin panel workflow (/panel/orders/<id>/)
    # so transitions are validated and stock is restored on cancellation;
    # payment status is only ever set by backend payment verification.
    list_display = ('id', 'user', 'total_price', 'status', 'payment_status', 'created_at')
    list_filter = ('status', 'payment_status', 'created_at')
    search_fields = ('id', 'user__username', 'payment_id', 'tracking_number')
    inlines = [OrderItemInline, PaymentInline]
    readonly_fields = (
        'status', 'payment_status', 'subtotal', 'discount', 'delivery_charge', 'total_price',
        'payment_id', 'razorpay_order_id', 'delivery_address', 'stock_deducted', 'created_at', 'updated_at',
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only record of gateway payments."""
    list_display = ('provider_order_id', 'order', 'user', 'amount', 'status', 'created_at')
    list_filter = ('status', 'provider', 'created_at')
    search_fields = ('provider_order_id', 'provider_payment_id', 'order__id', 'user__email')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('product__name', 'user__username', 'comment')


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ('sender', 'content', 'created_at', 'is_read')


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'seller', 'product', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('customer__username', 'seller__username', 'product__name')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'created_at', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__username', 'content', 'conversation__id')
    readonly_fields = ('sender', 'created_at', 'content')

@admin.register(HomeBanner)
class HomeBannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'is_active')
    list_editable = ('is_active',)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_type', 'discount_value', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('is_active', 'discount_type')
    search_fields = ('name',)
    filter_horizontal = ('products', 'categories')
