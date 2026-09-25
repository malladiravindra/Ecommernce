from django.contrib.auth.models import User
from rest_framework import serializers

from shop.models import Category, Product
from shop.serializers import validate_upload_image as validate_image_size  # type + size


class AdminCategorySerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'image', 'product_count']
        read_only_fields = ['slug']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Category name is required.")
        qs = Category.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value

    def validate_image(self, value):
        return validate_image_size(value)

    def update(self, instance, validated_data):
        # Keep the slug in sync with a renamed category.
        if 'name' in validated_data and validated_data['name'] != instance.name:
            instance.slug = ''
        return super().update(instance, validated_data)


class AdminCustomerSerializer(serializers.ModelSerializer):
    """Customer listing for admins. Never includes passwords or payment data."""
    full_name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    orders_count = serializers.IntegerField(read_only=True, default=0)
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, default=0)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'email', 'phone_number', 'is_active',
            'date_joined', 'last_login', 'orders_count', 'total_spent',
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_phone_number(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.phone_number if profile else ''


class ProductStockSerializer(serializers.ModelSerializer):
    """Lightweight product row for dashboard / inventory lists."""
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = ['id', 'name', 'category_name', 'price', 'final_price', 'stock', 'is_active', 'image', 'created_at']
