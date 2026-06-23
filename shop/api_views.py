from rest_framework import status, permissions, generics
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Product, Cart, CartItem, Wishlist, Review, Category, Order
from .serializers import (
    CartItemSerializer,
    CartSerializer,
    ReviewSerializer,
    CategorySerializer,
    ProductSerializer,
    WishlistSerializer,
    OrderSerializer,
)


class ProductListAPIView(generics.ListAPIView):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]


class ProductDetailAPIView(generics.RetrieveAPIView):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]


class CategoryListAPIView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class CategoryDetailAPIView(generics.RetrieveAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class CartDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        serializer = CartSerializer(cart)
        return Response(serializer.data)


class WishlistListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = WishlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class WishlistDestroyAPIView(generics.DestroyAPIView):
    serializer_class = WishlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user)


class ReviewListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Review.objects.all()
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    def perform_create(self, serializer):
        product = serializer.validated_data['product']
        if Review.objects.filter(product=product, user=self.request.user).exists():
            raise ValidationError({"product": "You have already reviewed this product."})
        serializer.save(user=self.request.user)


class OrderListAPIView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)


class AddToCartAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))

        if not product_id:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, id=product_id, is_active=True)

        if product.stock < quantity:
            return Response({"error": f"Only {product.stock} items available in stock."}, status=status.HTTP_400_BAD_REQUEST)

        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)

        if not created:
            cart_item.quantity += quantity
        else:
            cart_item.quantity = quantity

        cart_item.save()
        total_items = sum(item.quantity for item in cart.items.all())

        return Response({
            "message": f"Successfully added {product.name} to cart.",
            "cart_count": total_items
        }, status=status.HTTP_200_OK)


class UpdateCartItemAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        item_id = request.data.get('item_id')
        action = request.data.get('action')

        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)

        if action == 'increase':
            if cart_item.product.stock > cart_item.quantity:
                cart_item.quantity += 1
                cart_item.save()
            else:
                return Response({"error": "Maximum stock limit reached"}, status=status.HTTP_400_BAD_REQUEST)
        elif action == 'decrease':
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
            else:
                cart_item.delete()
        elif action == 'remove':
            cart_item.delete()

        cart = Cart.objects.get(user=request.user)
        total_items = sum(item.quantity for item in cart.items.all())
        cart_total = cart.get_total()

        return Response({
            "message": "Cart updated successfully.",
            "cart_count": total_items,
            "cart_total": cart_total
        }, status=status.HTTP_200_OK)


class ToggleWishlistAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get('product_id')
        if not product_id:
            return Response({"error": "Product ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, id=product_id)
        wishlist_item = Wishlist.objects.filter(user=request.user, product=product)

        if wishlist_item.exists():
            wishlist_item.delete()
            added = False
            message = "Removed from Wishlist"
        else:
            Wishlist.objects.create(user=request.user, product=product)
            added = True
            message = "Added to Wishlist"

        total_wishlist = Wishlist.objects.filter(user=request.user).count()

        return Response({
            "added": added,
            "message": message,
            "wishlist_count": total_wishlist
        }, status=status.HTTP_200_OK)


class CreateReviewAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ReviewSerializer(data=request.data)
        if serializer.is_valid():
            product = serializer.validated_data['product']
            if Review.objects.filter(product=product, user=request.user).exists():
                return Response({"error": "You have already reviewed this product."}, status=status.HTTP_400_BAD_REQUEST)
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
