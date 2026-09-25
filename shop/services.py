"""Checkout, order and inventory business rules.

Every write that touches stock runs inside a transaction with the affected
product rows locked (select_for_update), so two concurrent payments can't
both consume the last unit.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F

from .models import Cart, CartItem, Order, OrderItem, Payment, Product

TWO_PLACES = Decimal('0.01')
REQUIRED_ADDRESS_FIELDS = ('full_name', 'phone', 'address_line1', 'city', 'state', 'postal_code', 'country')


class CheckoutError(Exception):
    """A customer-facing validation failure (cart, stock, address, order state)."""

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.message = message
        self.problems = problems or []


def _money(value):
    return Decimal(value).quantize(TWO_PLACES)


def calculate_totals(lines):
    """`lines` is an iterable of (product, quantity).

    subtotal  = list price x qty
    discount  = (list price - selling price) x qty
    delivery  = settings.DELIVERY_CHARGE, waived at FREE_DELIVERY_MIN_ORDER
    total     = subtotal - discount + delivery
    """
    subtotal = Decimal('0')
    discount = Decimal('0')
    for product, quantity in lines:
        subtotal += product.price * quantity
        discount += (product.price - product.final_price) * quantity
    items_total = subtotal - discount

    delivery_charge = _money(settings.DELIVERY_CHARGE or 0)
    free_from = _money(settings.FREE_DELIVERY_MIN_ORDER or 0)
    if items_total <= 0 or (free_from > 0 and items_total >= free_from):
        delivery_charge = Decimal('0')

    return {
        'subtotal': _money(subtotal),
        'discount': _money(discount),
        'delivery_charge': _money(delivery_charge),
        'total': _money(items_total + delivery_charge),
    }


def cart_summary(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    items = list(cart.items.select_related('product'))
    return cart, items, calculate_totals((i.product, i.quantity) for i in items)


def validate_stock(lines, require_active=True):
    """Return a list of human-readable problems for (product, quantity) lines."""
    problems = []
    for product, quantity in lines:
        if product is None:
            problems.append("A product in your order no longer exists.")
        elif require_active and not product.is_active:
            problems.append(f"{product.name} is no longer available.")
        elif quantity < 1:
            problems.append(f"Invalid quantity for {product.name}.")
        elif quantity > product.stock:
            problems.append(f"Only {product.stock} unit(s) of {product.name} left in stock.")
    return problems


def address_snapshot(address):
    missing = [f for f in REQUIRED_ADDRESS_FIELDS if not (getattr(address, f, '') or '').strip()]
    if missing:
        raise CheckoutError("The delivery address is incomplete.", [f"Missing {f.replace('_', ' ')}." for f in missing])
    return {
        'full_name': address.full_name,
        'phone': address.phone,
        'address_line1': address.address_line1,
        'address_line2': address.address_line2 or '',
        'city': address.city,
        'state': address.state,
        'postal_code': address.postal_code,
        'country': address.country,
    }


def create_order_from_cart(user, address):
    """Validate the cart and create a PENDING order. Stock is NOT reduced here."""
    with transaction.atomic():
        cart, items, _ = cart_summary(user)
        if not items:
            raise CheckoutError("Your cart is empty.")
        snapshot = address_snapshot(address)

        # Re-read products with a lock so the stock check is consistent.
        products = Product.objects.select_for_update().in_bulk([i.product_id for i in items])
        lines = [(products.get(i.product_id), i.quantity) for i in items]
        problems = validate_stock(lines)
        if problems:
            raise CheckoutError("Some items in your cart can't be ordered.", problems)

        totals = calculate_totals(lines)
        order = Order.objects.create(
            user=user,
            shipping_address=address,
            delivery_address=snapshot,
            status=Order.PENDING,
            subtotal=totals['subtotal'],
            discount=totals['discount'],
            delivery_charge=totals['delivery_charge'],
            total_price=totals['total'],
            payment_status=False,
        )
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=p, product_name=p.name, price=p.final_price, quantity=q)
            for p, q in lines
        ])
    return order


# Outcomes of applying a verified payment to its order.
CONFIRMED = 'confirmed'            # this payment confirmed the order
ALREADY_PROCESSED = 'already_processed'  # this payment was applied before (replay)
REFUND_REQUIRED = 'refund_required'      # captured, but the order can't take it


class _StockShortage(Exception):
    pass


def _flag_refund(payment, reason):
    payment.refund_status = Payment.REFUND_REQUIRED
    payment.refund_reason = reason[:255]


def confirm_paid_order(payment, provider_payment_id):
    """Apply a gateway-verified payment. Returns (order, outcome).

    Runs in one transaction with the payment and order rows locked, so the
    browser verification, a webhook and any replays are serialized and only
    the first one does any work (idempotent).

    - PENDING, unpaid order + enough stock -> payment SUCCESS, order CONFIRMED,
      stock deducted exactly once (conditional UPDATE: stock never negative).
    - Order already paid by another payment, or cancelled/expired before the
      money arrived, or out of stock -> payment SUCCESS with refund REQUIRED.
      A confirmed order is never cancelled by a second payment.
    """
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        if payment.status in (Payment.SUCCESS, Payment.REFUNDED):
            return order, ALREADY_PROCESSED

        payment.status = Payment.SUCCESS
        payment.provider_payment_id = provider_payment_id
        payment.failure_reason = ''

        if order.payment_status:
            _flag_refund(payment, f"Duplicate payment: order #{order.pk} was already paid.")
            payment.save()
            return order, REFUND_REQUIRED

        if order.status != Order.PENDING:
            _flag_refund(payment, f"Payment arrived after the order was {order.get_status_display().lower()}.")
            payment.save()
            order.payment_status = True
            order.payment_id = provider_payment_id
            order.cancellation_reason = (
                (order.cancellation_reason + ' ' if order.cancellation_reason else '') + 'Paid after cancellation — refund required.'
            )[:255]
            order.save(update_fields=['payment_status', 'payment_id', 'cancellation_reason', 'updated_at'])
            return order, REFUND_REQUIRED

        if payment.amount != order.total_price:
            # The gateway order is always created from order.total_price, so
            # this means tampering or a bug — never confirm on a mismatch.
            _flag_refund(payment, f"Amount mismatch: paid {payment.amount}, order total {order.total_price}.")
            payment.save()
            return order, REFUND_REQUIRED

        payment.save()
        order.payment_status = True
        order.payment_id = provider_payment_id
        items = list(order.items.all())
        try:
            with transaction.atomic():  # savepoint: all-or-nothing stock deduction
                for item in items:
                    updated = Product.objects.filter(pk=item.product_id, stock__gte=item.quantity).update(
                        stock=F('stock') - item.quantity
                    ) if item.product_id else 0
                    if not updated:
                        raise _StockShortage(f"{item.product_name} is out of stock.")
        except _StockShortage as shortage:
            _flag_refund(payment, str(shortage))
            payment.save(update_fields=['refund_status', 'refund_reason', 'updated_at'])
            order.status = Order.CANCELLED
            order.cancellation_reason = f"Paid but could not be fulfilled — refund required. {shortage}"[:255]
            order.save()
            return order, REFUND_REQUIRED

        order.stock_deducted = True
        order.status = Order.CONFIRMED
        order.tracking_number = order.tracking_number or f"TRK{uuid.uuid4().hex[:10].upper()}"
        order.save()

        # Only the purchased products leave the cart; anything added since stays.
        if order.user_id:
            CartItem.objects.filter(
                cart__user_id=order.user_id, product_id__in=[i.product_id for i in items if i.product_id]
            ).delete()
    return order, CONFIRMED


def update_order_status(order, new_status, tracking_number=None, reason=''):
    """Admin status change with transition rules; cancelling restocks once."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if new_status == order.status:
            raise CheckoutError(f"Order is already {order.get_status_display()}.")
        if not order.can_transition_to(new_status):
            raise CheckoutError(
                f"Cannot change status from {order.get_status_display()} to {dict(Order.STATUS_CHOICES).get(new_status, new_status)}."
            )

        if new_status == Order.CANCELLED:
            # stock_deducted is the single source of truth: restock only if
            # this order actually took stock, and clear the flag in the same
            # transaction so it can never be restored twice.
            if order.stock_deducted:
                for item in order.items.all():
                    if item.product_id:
                        Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.quantity)
                order.stock_deducted = False
            order.cancellation_reason = (reason or 'Cancelled by admin.')[:255]
            refundable = order.payments.select_for_update().filter(status=Payment.SUCCESS, refund_status=Payment.REFUND_NONE)
            if refundable.exists():
                refundable.update(refund_status=Payment.REFUND_REQUIRED, refund_reason='Order cancelled after payment.')
                order.cancellation_reason = (order.cancellation_reason + ' Refund required.')[:255]
            # Any payment attempt still open for this order can no longer succeed normally.
            order.payments.filter(status=Payment.PENDING).update(status=Payment.FAILED, failure_reason='Order cancelled')

        if tracking_number:
            order.tracking_number = tracking_number
        order.status = new_status
        order.save()
    return order


def expire_pending_orders(timeout_minutes=None, now=None):
    """Cancel unpaid PENDING orders with no activity for `timeout_minutes`.

    Uses the existing CANCELLED status (PENDING -> CANCELLED is an allowed
    transition) with an explanatory reason rather than a new status. An order
    with a payment attempt started inside the window is left alone. If money
    for an expired order still arrives later, confirm_paid_order records it
    as SUCCESS with refund REQUIRED. Unpaid orders never deducted stock, so
    nothing is restocked. Returns the number of orders expired.
    """
    from datetime import timedelta
    from django.utils import timezone

    minutes = settings.PENDING_ORDER_TIMEOUT_MINUTES if timeout_minutes is None else timeout_minutes
    cutoff = (now or timezone.now()) - timedelta(minutes=minutes)
    candidate_ids = list(
        Order.objects.filter(status=Order.PENDING, payment_status=False, created_at__lt=cutoff)
        .exclude(payments__created_at__gte=cutoff)
        .values_list('pk', flat=True).distinct()
    )
    expired = 0
    for pk in candidate_ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=pk)
            if order.status != Order.PENDING or order.payment_status:
                continue
            order.status = Order.CANCELLED
            order.cancellation_reason = f"Expired: payment was not completed within {minutes} minutes."
            order.save(update_fields=['status', 'cancellation_reason', 'updated_at'])
            order.payments.filter(status=Payment.PENDING).update(status=Payment.FAILED, failure_reason='Order expired')
            expired += 1
    return expired


def process_razorpay_webhook(event_id, payload):
    """Apply a signature-verified Razorpay webhook. Idempotent.

    Returns a short result string for logging/response.
    """
    import logging
    from .models import PaymentWebhookEvent

    log = logging.getLogger(__name__)
    event = payload.get('event', '')
    entities = payload.get('payload', {})

    with transaction.atomic():
        if event_id:
            _, created = PaymentWebhookEvent.objects.get_or_create(event_id=event_id, defaults={'event_type': event[:60]})
            if not created:
                return 'duplicate_event'

        if event in ('payment.captured', 'order.paid'):
            entity = entities.get('payment', {}).get('entity', {})
            payment = Payment.objects.filter(provider_order_id=entity.get('order_id') or '').first()
            if not payment:
                log.warning("razorpay webhook %s: unknown gateway order %s", event, entity.get('order_id'))
                return 'ignored_unknown_order'
            expected_paise = int(payment.amount * 100)
            if int(entity.get('amount') or 0) != expected_paise or (entity.get('currency') or '') != payment.currency:
                log.error("razorpay webhook %s: amount/currency mismatch for payment id=%s", event, payment.pk)
                with transaction.atomic():
                    locked = Payment.objects.select_for_update().get(pk=payment.pk)
                    _flag_refund(locked, "Gateway amount/currency did not match the order.")
                    locked.save(update_fields=['refund_status', 'refund_reason', 'updated_at'])
                return 'rejected_amount_mismatch'
            _, outcome = confirm_paid_order(payment, entity.get('id') or '')
            return outcome

        if event == 'payment.failed':
            entity = entities.get('payment', {}).get('entity', {})
            updated = Payment.objects.filter(
                provider_order_id=entity.get('order_id') or '', status=Payment.PENDING
            ).update(status=Payment.FAILED, failure_reason=(entity.get('error_description') or 'Payment failed')[:255])
            return 'payment_failed' if updated else 'ignored'

        if event == 'refund.processed':
            entity = entities.get('refund', {}).get('entity', {})
            updated = Payment.objects.filter(
                provider_payment_id=entity.get('payment_id') or '', status=Payment.SUCCESS
            ).update(status=Payment.REFUNDED, refund_status=Payment.REFUND_PROCESSED)
            return 'refund_processed' if updated else 'ignored'

    return 'ignored'
