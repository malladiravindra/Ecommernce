from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP

# Offers may never take a selling price below this (Razorpay needs a
# positive amount, and a free item is a business decision, not an offer).
MIN_SELLING_PRICE = Decimal('1.00')

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
    # PROTECT: a category with products can't be deleted (no cascading catalogue loss).
    category = models.ForeignKey(Category, related_name='products', on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    stock = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    is_highlight = models.BooleanField(default=False)
    # Admin-controlled "NEW LAUNCH" flag shown on the storefront.
    is_new_launch = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'product'
            slug, n = base, 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def active_offer(self):
        """Best currently-active Offer for this product (or None). Cached per
        instance; list views pre-attach it via shop.offers.attach_offers()."""
        if not hasattr(self, '_active_offer'):
            from .offers import active_offers, best_offer_for
            self._active_offer = best_offer_for(self, active_offers())
        return self._active_offer

    @property
    def final_price(self):
        """The price the customer pays: the lowest of list price, the
        product's own discount price and the best active offer (no stacking).
        Used for display, cart, checkout and the Razorpay amount alike."""
        candidates = [self.price]
        if self.discount_price and self.discount_price < self.price:
            candidates.append(self.discount_price)
        offer = self.active_offer
        if offer:
            candidates.append(offer.price_for(self.price))
        return min(candidates)

    @property
    def savings(self):
        return self.price - self.final_price

    @property
    def offer_applied(self):
        """The active offer only if it is what sets final_price."""
        offer = self.active_offer
        return offer if offer and offer.price_for(self.price) == self.final_price and self.final_price < self.price else None

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


class OfferQuerySet(models.QuerySet):
    def active(self, now=None):
        now = now or timezone.now()
        return self.filter(is_active=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now),
            Q(ends_at__isnull=True) | Q(ends_at__gt=now),
        )


class Offer(models.Model):
    """Admin-managed promotion applied to selected products and/or categories."""
    PERCENT = 'PERCENT'
    FLAT = 'FLAT'
    DISCOUNT_TYPES = ((PERCENT, 'Percentage off'), (FLAT, 'Flat amount off'))

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPES, default=PERCENT)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    products = models.ManyToManyField(Product, blank=True, related_name='offers')
    categories = models.ManyToManyField(Category, blank=True, related_name='offers')
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OfferQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']

    def price_for(self, list_price):
        """Offer price for a list price, or the list price if the offer
        would push it below MIN_SELLING_PRICE (offer not applicable)."""
        if self.discount_type == self.PERCENT:
            price = list_price * (Decimal('100') - self.discount_value) / Decimal('100')
        else:
            price = list_price - self.discount_value
        price = price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return price if price >= MIN_SELLING_PRICE else list_price

    @property
    def is_live(self):
        now = timezone.now()
        return self.is_active and (not self.starts_at or self.starts_at <= now) and (not self.ends_at or self.ends_at > now)

    @property
    def label(self):
        if self.discount_type == self.PERCENT:
            return f"{self.discount_value.normalize():f}% off"
        return f"₹{self.discount_value} off"

    def __str__(self):
        return self.name


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
    PENDING = 'PENDING'
    CONFIRMED = 'CONFIRMED'
    PROCESSING = 'PROCESSING'
    SHIPPED = 'SHIPPED'
    OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY'
    DELIVERED = 'DELIVERED'
    CANCELLED = 'CANCELLED'
    STATUS_CHOICES = (
        (PENDING, 'Pending'),
        (CONFIRMED, 'Confirmed'),
        (PROCESSING, 'Processing'),
        (SHIPPED, 'Shipped'),
        (OUT_FOR_DELIVERY, 'Out for delivery'),
        (DELIVERED, 'Delivered'),
        (CANCELLED, 'Cancelled'),
    )
    # Admin-driven transitions. PENDING -> CONFIRMED only happens through
    # backend payment verification, never by hand.
    ALLOWED_TRANSITIONS = {
        PENDING: {CANCELLED},
        CONFIRMED: {PROCESSING, CANCELLED},
        PROCESSING: {SHIPPED, CANCELLED},
        SHIPPED: {OUT_FOR_DELIVERY, DELIVERED},
        OUT_FOR_DELIVERY: {DELIVERED},
        DELIVERED: set(),
        CANCELLED: set(),
    }
    # Step index used by the customer tracking bar.
    TRACKING_STEPS = [CONFIRMED, PROCESSING, SHIPPED, OUT_FOR_DELIVERY, DELIVERED]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='orders')
    shipping_address = models.ForeignKey(ShippingAddress, on_delete=models.SET_NULL, null=True)
    # Snapshot of the delivery address at order time, so later edits to the
    # saved address never change where a past order was shipped.
    delivery_address = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_id = models.CharField(max_length=255, blank=True, null=True)
    payment_status = models.BooleanField(default=False)
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    stock_deducted = models.BooleanField(default=False)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def can_transition_to(self, new_status):
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, set())

    @property
    def tracking_step(self):
        """1-based position in TRACKING_STEPS (0 = not yet confirmed)."""
        if self.status in self.TRACKING_STEPS:
            return self.TRACKING_STEPS.index(self.status) + 1
        return 0

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


class Payment(models.Model):
    """One payment attempt for an order through the gateway.

    Only gateway references are stored — never card numbers, CVV, UPI PINs
    or any other payment credential.
    """
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    REFUNDED = 'REFUNDED'
    STATUS_CHOICES = (
        (PENDING, 'Pending'),
        (SUCCESS, 'Success'),
        (FAILED, 'Failed'),
        (REFUNDED, 'Refunded'),
    )
    # Refunds are issued manually from the Razorpay dashboard. A captured
    # payment whose order can't be fulfilled is flagged REQUIRED; it only
    # becomes PROCESSED (and status REFUNDED) when Razorpay's refund.processed
    # webhook confirms it — never on an admin's say-so.
    REFUND_NONE = 'NONE'
    REFUND_REQUIRED = 'REQUIRED'
    REFUND_PROCESSED = 'PROCESSED'
    REFUND_CHOICES = (
        (REFUND_NONE, 'Not required'),
        (REFUND_REQUIRED, 'Refund required'),
        (REFUND_PROCESSED, 'Refunded'),
    )

    order = models.ForeignKey(Order, related_name='payments', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='payments')
    provider = models.CharField(max_length=30, default='razorpay')
    provider_order_id = models.CharField(max_length=100, unique=True)
    provider_payment_id = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    failure_reason = models.CharField(max_length=255, blank=True)
    refund_status = models.CharField(max_length=10, choices=REFUND_CHOICES, default=REFUND_NONE)
    refund_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.provider_order_id} ({self.status}) for order #{self.order_id}"


class PaymentWebhookEvent(models.Model):
    """Razorpay webhook deliveries already processed (X-Razorpay-Event-Id),
    so a redelivered event is acknowledged without being applied twice."""
    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=60)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} {self.event_id}"


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
