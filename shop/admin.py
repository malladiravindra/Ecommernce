from django.contrib import admin
from .models import (
    Category, Product, ProductImage, Cart, CartItem, 
    Wishlist, ShippingAddress, Order, OrderItem, Review,
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
    list_display = ('name', 'category', 'price', 'discount_price', 'stock', 'is_active', 'featured', 'is_highlight', 'created_at')
    list_filter = ('is_active', 'featured', 'is_highlight', 'category', 'created_at')
    list_editable = ('price', 'discount_price', 'stock', 'is_active', 'featured', 'is_highlight')
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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'total_price', 'status', 'payment_status', 'created_at')
    list_filter = ('status', 'payment_status', 'created_at')
    list_editable = ('status', 'payment_status')
    search_fields = ('id', 'user__username', 'payment_id', 'tracking_number')
    inlines = [OrderItemInline]
    readonly_fields = ('total_price', 'payment_id', 'created_at', 'updated_at')


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
