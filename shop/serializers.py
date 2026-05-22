from rest_framework import serializers
from .models import Product, Category, Review, CartItem, Wishlist
from django.contrib.auth.models import User

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


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    average_rating = serializers.ReadOnlyField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'category', 'name', 'slug', 'description', 'price', 
            'discount_price', 'final_price', 'image', 'stock', 
            'is_active', 'featured', 'average_rating'
        ]


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    subtotal = serializers.ReadOnlyField(source='get_subtotal')
    
    class Meta:
        model = CartItem
        fields = ['id', 'product', 'quantity', 'subtotal']


class WishlistSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    
    class Meta:
        model = Wishlist
        fields = ['id', 'product', 'added_at']
