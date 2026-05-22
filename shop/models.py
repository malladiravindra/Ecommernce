from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)

    class Meta:
        verbose_name_plural = 'Categories'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    stock = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    is_highlight = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def final_price(self):
        if self.discount_price and self.discount_price < self.price:
            return self.discount_price
        return self.price

    @property
    def average_rating(self):
        reviews = self.reviews.all()
        if reviews.exists():
            return sum(review.rating for review in reviews) / reviews.count()
        return 0.0

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='products/gallery/')

    def __str__(self):
        return f"Gallery Image for {self.product.name}"


class Cart(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)

    def get_total(self):
        return sum(item.get_subtotal() for item in self.items.all())

    def __str__(self):
        return f"Cart of {self.user.username}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def get_subtotal(self):
        try:
            if not self.product:
                return 0.00
            return self.product.final_price * self.quantity
        except Exception:
            return 0.00

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"


class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')

    def __str__(self):
        return f"{self.user.username} wishlist: {self.product.name}"


class ShippingAddress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=150, default='')
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='India')
    phone = models.CharField(max_length=20, default='')

    def __str__(self):
        return f"{self.full_name} - {self.city}, {self.postal_code}"


class Order(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    )

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='orders')
    shipping_address = models.ForeignKey(ShippingAddress, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_id = models.CharField(max_length=255, blank=True, null=True)
    payment_status = models.BooleanField(default=False)
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} by {self.user.username if self.user else 'Deleted User'}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=200) # Store historical name
    price = models.DecimalField(max_digits=10, decimal_places=2) # Historical price at checkout
    quantity = models.PositiveIntegerField(default=1)

    def get_subtotal(self):
        if self.price is None:
            return 0.00
        return self.price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"


class Review(models.Model):
    product = models.ForeignKey(Product, related_name='reviews', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('product', 'user')

    def __str__(self):
        return f"{self.user.username} review on {self.product.name}"


class Conversation(models.Model):
    """Represents a chat conversation between a customer and a seller."""
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_customer')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_seller')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('customer', 'seller', 'product')
        ordering = ['-updated_at']

    def __str__(self):
        return f"Chat: {self.customer.username} & {self.seller.username}"


class Message(models.Model):
    """Individual message in a conversation."""
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message by {self.sender.username} in {self.conversation}"

class HomeBanner(models.Model):
    subtitle = models.CharField(max_length=100, default='New Arrivals 2026')
    title = models.CharField(max_length=200, default='Elevated Living, Curated for You')
    description = models.TextField(default='Immerse yourself in our handpicked collections where craftsmanship meets modern design philosophies.')
    button_text = models.CharField(max_length=50, default='Explore Catalog')
    button_link = models.CharField(max_length=200, default='/products/')
    image = models.ImageField(upload_to='banners/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title
