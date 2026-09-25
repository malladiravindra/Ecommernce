import re

from rest_framework import serializers
from .models import (
    Product, ProductImage, Category, Review, CartItem, Wishlist, Cart,
    Order, OrderItem, ShippingAddress, Payment, Offer,
)
from django.contrib.auth.models import User

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp', 'gif')


def validate_upload_image(image):
    """Uploaded images: real image content (checked by ImageField/Pillow),
    an image file extension (so a valid image can't be stored as .html/.svg
    and served as active content), and at most 5 MB."""
    if not image:
        return image
    ext = image.name.rsplit('.', 1)[-1].lower() if '.' in image.name else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError(f"Unsupported image type. Allowed: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}.")
    if image.size > MAX_IMAGE_BYTES:
        raise serializers.ValidationError("Image must be 5 MB or smaller.")
    return image


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'image']


class ReviewSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'product', 'user', 'rating', 'comment', 'created_at']
        read_only_fields = ['user']


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image']


class OfferSummarySerializer(serializers.ModelSerializer):
    label = serializers.ReadOnlyField()

    class Meta:
        model = Offer
        fields = ['id', 'name', 'label', 'discount_type', 'discount_value', 'ends_at']


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    average_rating = serializers.ReadOnlyField()
    images = ProductImageSerializer(many=True, read_only=True)
    in_stock = serializers.SerializerMethodField()
    savings = serializers.ReadOnlyField()
    offer = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'category', 'name', 'slug', 'brand', 'description', 'price',
            'discount_price', 'final_price', 'savings', 'offer', 'image', 'images', 'stock', 'in_stock',
            'is_active', 'featured', 'is_new_launch', 'average_rating'
        ]

    def get_in_stock(self, obj):
        return obj.stock > 0

    def get_offer(self, obj):
        offer = obj.offer_applied
        return OfferSummarySerializer(offer).data if offer else None


class OfferSerializer(serializers.ModelSerializer):
    """Public, read-only view of a live offer."""
    label = serializers.ReadOnlyField()

    class Meta:
        model = Offer
        fields = ['id', 'name', 'description', 'label', 'discount_type', 'discount_value',
                  'products', 'categories', 'starts_at', 'ends_at']


class AdminOfferSerializer(serializers.ModelSerializer):
    label = serializers.ReadOnlyField()
    is_live = serializers.ReadOnlyField()
    products = serializers.PrimaryKeyRelatedField(many=True, queryset=Product.objects.all(), required=False)
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=Category.objects.all(), required=False)
    product_names = serializers.SerializerMethodField()
    category_names = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = ['id', 'name', 'description', 'discount_type', 'discount_value', 'label', 'products',
                  'categories', 'product_names', 'category_names', 'starts_at', 'ends_at', 'is_active',
                  'is_live', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_product_names(self, obj):
        return [p.name for p in obj.products.all()]

    def get_category_names(self, obj):
        return [c.name for c in obj.categories.all()]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Offer name is required.")
        return value

    def _current(self, attrs, key):
        if key in attrs:
            return attrs[key]
        return getattr(self.instance, key, None) if self.instance else None

    def validate(self, attrs):
        discount_type = self._current(attrs, 'discount_type') or Offer.PERCENT
        value = self._current(attrs, 'discount_value')
        if value is not None:
            if value <= 0:
                raise serializers.ValidationError({'discount_value': "Discount must be greater than zero."})
            if discount_type == Offer.PERCENT and value >= 100:
                raise serializers.ValidationError({'discount_value': "A percentage discount must be below 100."})
        starts, ends = self._current(attrs, 'starts_at'), self._current(attrs, 'ends_at')
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({'ends_at': "End date must be after the start date."})
        if 'products' in attrs:
            products = attrs['products']
        else:
            products = list(self.instance.products.all()) if self.instance else []
        if 'categories' in attrs:
            categories = attrs['categories']
        else:
            categories = list(self.instance.categories.all()) if self.instance else []
        if not products and not categories:
            raise serializers.ValidationError({'products': "Choose at least one product or category."})
        return attrs


class AdminProductSerializer(serializers.ModelSerializer):
    """Create/update products from the admin panel (multipart for images)."""
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    category_name = serializers.CharField(source='category.name', read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    final_price = serializers.ReadOnlyField()
    # Explicit default: in multipart/form data an omitted boolean would
    # otherwise be read as False and silently create a hidden product.
    is_active = serializers.BooleanField(default=True)
    offer = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'brand', 'description', 'category', 'category_name',
            'price', 'discount_price', 'final_price', 'offer', 'stock', 'is_active', 'featured',
            'is_highlight', 'is_new_launch', 'image', 'images', 'created_at', 'updated_at',
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def get_offer(self, obj):
        offer = obj.offer_applied
        return OfferSummarySerializer(offer).data if offer else None

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Product name is required.")
        return value

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value

    def validate_image(self, value):
        return validate_upload_image(value)

    def validate(self, attrs):
        price = attrs.get('price', getattr(self.instance, 'price', None))
        discount = attrs.get('discount_price', getattr(self.instance, 'discount_price', None))
        if discount is not None:
            if discount <= 0:
                raise serializers.ValidationError({'discount_price': "Discount price must be greater than zero."})
            if price is not None and discount >= price:
                raise serializers.ValidationError({'discount_price': "Discount price must be lower than the price."})
        return attrs


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    subtotal = serializers.ReadOnlyField(source='get_subtotal')

    class Meta:
        model = CartItem
        fields = ['id', 'product', 'quantity', 'subtotal']


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ['id', 'user', 'items', 'total']
        read_only_fields = ['user']

    def get_total(self, obj):
        return obj.get_total()


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShippingAddress
        fields = [
            'id', 'full_name', 'phone', 'address_line1', 'address_line2',
            'city', 'state', 'postal_code', 'country',
        ]
        extra_kwargs = {
            'full_name': {'required': True, 'allow_blank': False},
            'phone': {'required': True, 'allow_blank': False},
            'address_line2': {'required': False, 'allow_blank': True, 'allow_null': True},
        }

    def validate(self, attrs):
        for key, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[key] = value.strip()
        for key in ('full_name', 'address_line1', 'city', 'state', 'postal_code', 'phone'):
            if key in attrs and not attrs[key]:
                raise serializers.ValidationError({key: "This field may not be blank."})
        return attrs

    def validate_phone(self, value):
        digits = re.sub(r"[\s\-()]", "", value or "")
        if not re.fullmatch(r"\+?\d{7,15}", digits):
            raise serializers.ValidationError("Enter a valid phone number (7-15 digits).")
        return digits

    def validate_postal_code(self, value):
        value = (value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9 \-]{3,10}", value):
            raise serializers.ValidationError("Enter a valid postal code.")
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.ReadOnlyField(source='get_subtotal')
    product_slug = serializers.CharField(source='product.slug', read_only=True, default=None)

    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'product_slug', 'product_name', 'price', 'quantity', 'subtotal']


class PaymentSummarySerializer(serializers.ModelSerializer):
    """Public payment info — gateway references only, never credentials."""
    class Meta:
        model = Payment
        fields = [
            'id', 'provider', 'provider_order_id', 'provider_payment_id', 'amount', 'currency', 'status',
            'failure_reason', 'refund_status', 'refund_reason', 'created_at',
        ]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'status', 'status_display', 'tracking_step', 'subtotal', 'discount',
            'delivery_charge', 'total_price', 'payment_status', 'payment',
            'delivery_address', 'tracking_number', 'cancellation_reason',
            'created_at', 'updated_at', 'items'
        ]
        read_only_fields = fields

    def get_payment(self, obj):
        payment = obj.payments.first()
        return PaymentSummarySerializer(payment).data if payment else None


class AdminOrderSerializer(OrderSerializer):
    customer = serializers.SerializerMethodField()
    payments = PaymentSummarySerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ['customer', 'payments', 'stock_deducted', 'allowed_transitions']
        read_only_fields = fields

    def get_customer(self, obj):
        if not obj.user:
            return None
        return {
            'id': obj.user.id,
            'username': obj.user.username,
            'full_name': obj.user.get_full_name(),
            'email': obj.user.email,
        }

    def get_allowed_transitions(self, obj):
        return sorted(Order.ALLOWED_TRANSITIONS.get(obj.status, set()), key=[c for c, _ in Order.STATUS_CHOICES].index)


class WishlistSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    class Meta:
        model = Wishlist
        fields = ['id', 'product', 'added_at']
