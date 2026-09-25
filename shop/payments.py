"""Razorpay gateway integration.

The backend creates the gateway order (so the amount is always set
server-side) and verifies the HMAC-SHA256 signature Razorpay returns after
payment. Only gateway reference IDs are ever stored.
"""
import hashlib
import hmac
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class PaymentGatewayError(Exception):
    pass


class PaymentGatewayNotConfigured(PaymentGatewayError):
    pass


def is_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _client():
    if not is_configured():
        raise PaymentGatewayNotConfigured("Payment gateway is not configured.")
    import razorpay
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_gateway_order(amount_paise, receipt, notes=None):
    """Create a Razorpay order and return its id."""
    try:
        gateway_order = _client().order.create({
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': receipt,
            'notes': notes or {},
            'payment_capture': 1,
        })
    except PaymentGatewayNotConfigured:
        raise
    except Exception as error:
        logger.exception("Razorpay order creation failed (receipt=%s)", receipt)
        raise PaymentGatewayError("Could not reach the payment gateway.") from error
    return gateway_order['id']


def verify_webhook_signature(raw_body, signature):
    """Razorpay webhook signature = HMAC_SHA256(raw request body, webhook secret)."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not (secret and signature and raw_body is not None):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


def verify_signature(gateway_order_id, gateway_payment_id, signature):
    """Razorpay signature = HMAC_SHA256(order_id + "|" + payment_id, key_secret)."""
    if not (is_configured() and gateway_order_id and gateway_payment_id and signature):
        return False
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        f"{gateway_order_id}|{gateway_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, str(signature))
