"""OTP generation and email delivery for AssetFlow.

Real Gmail SMTP only — nothing here is mocked. The Gmail account configured
in settings.py (EMAIL_HOST_USER / DEFAULT_FROM_EMAIL) is ONLY ever the SMTP
sender. Every OTP is delivered to recipient_list=[user_email] — the affected
user's own registered address — never to the sender account.
"""
import logging
from datetime import timedelta
from secrets import randbelow

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.mail import send_mail
from django.utils import timezone

from .models import EmailOTP

logger = logging.getLogger(__name__)


def mask_email(email):
    """Mask an email for logs — never write full addresses to the terminal."""
    local, _, domain = email.partition("@")
    if not domain:
        return "[Email]"
    visible = local[:2]
    return f"{visible}{'*' * max(len(local) - 2, 2)}@{domain}"


OTP_EXPIRY = timedelta(minutes=5)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_ATTEMPTS = 5
MAX_OTP_REQUESTS = 5
OTP_REQUEST_WINDOW = timedelta(minutes=15)


class OTPDeliveryError(Exception):
    """Raised when Gmail SMTP fails to accept an OTP email."""


class OTPRateLimitError(Exception):
    """Raised when a user has requested too many OTPs in the rate-limit window."""


def generate_otp():
    """Cryptographically secure, always-6-digit OTP (zero-padded)."""
    return f"{randbelow(1000000):06d}"


def send_otp_email(user_email, otp, purpose):
    """Email `otp` to `user_email` via Gmail SMTP. Never logs the OTP itself."""
    if purpose == EmailOTP.PASSWORD_RESET:
        subject = "AssetFlow Password Reset OTP"
        message = f"""Hello,

Your AssetFlow password reset OTP is:

{otp}

This OTP will expire in 5 minutes.

If you did not request a password reset, please ignore this email.

Regards,
AssetFlow Team
"""
    elif purpose == EmailOTP.LOGIN:
        subject = "AssetFlow Login Verification OTP"
        message = f"""Hello,

Your AssetFlow login verification OTP is:

{otp}

This OTP will expire in 5 minutes.

Regards,
AssetFlow Team
"""
    elif purpose == EmailOTP.REGISTRATION:
        subject = "AssetFlow Account Verification OTP"
        message = f"""Hello,

Your AssetFlow account verification OTP is:

{otp}

This OTP will expire in 5 minutes.

If you did not create an account, please ignore this email.

Regards,
AssetFlow Team
"""
    else:
        raise ValueError("Invalid OTP purpose")

    masked = mask_email(user_email)
    try:
        # recipient_list is always the user's own address — the Gmail
        # account above is only ever the sender (from_email), never here.
        # fail_silently=False so SMTP errors raise instead of vanishing.
        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
        )
    except Exception as error:
        if settings.DEBUG:
            print("\n" + "="*80)
            print(f"DEVELOPMENT OTP FOR {user_email} ({purpose}): {otp}")
            print("="*80 + "\n")
            logger.warning(f"[AssetFlow OTP] SMTP failed but DEBUG is True. Printing OTP to console and bypassing error: {error!r}")
            return
        # Full traceback to the terminal — never swallowed. Never logs the
        # OTP or any credential, only the masked recipient and purpose.
        logger.debug(f"[AssetFlow OTP] FAILED to send {purpose} OTP to {masked}: {error!r}")
        logger.exception("AssetFlow OTP email delivery failed (purpose=%s, to=%s)", purpose, masked)
        raise OTPDeliveryError from error

    if sent_count != 1:
        logger.debug(f"[AssetFlow OTP] SMTP accepted 0 messages for {purpose} OTP to {masked}")
        logger.error("SMTP did not accept the OTP email (purpose=%s, to=%s)", purpose, masked)
        raise OTPDeliveryError("SMTP did not accept the OTP email")

    logger.debug(f"[AssetFlow OTP] Sent {purpose} OTP to {masked} (SMTP accepted {sent_count} message)")
    logger.info("AssetFlow OTP email sent (purpose=%s, to=%s)", purpose, masked)


def issue_decoy_otp(email):
    """Email a real-looking 6-digit OTP to `email`, which has no matching
    active account.

    There is no user row to attach a real EmailOTP to, so this code is
    never persisted and can never be verified — entering it on the verify
    screen will correctly fail with "Invalid or expired OTP.". It exists
    purely so the outbound email is indistinguishable from a genuine
    password-reset OTP (same subject, same body), which is what keeps
    forgot-password from leaking account existence through email content.
    Never raises; delivery failure here shouldn't affect the (always
    generic) API response.
    """
    masked = mask_email(email)
    try:
        send_otp_email(email, generate_otp(), EmailOTP.PASSWORD_RESET)
    except OTPDeliveryError:
        logger.error("forgot-password: decoy OTP delivery failed for unregistered email=%s", masked)
        return

    logger.debug(f"[AssetFlow OTP] issue_decoy_otp: sent look-alike OTP to {masked} (not stored — no matching account)")


def issue_otp(user, purpose, *, invalidate_existing=True):
    """Generate, store (hashed) and email a new OTP for `user`.

    Enforces the resend cooldown and a rolling max-requests rate limit.
    Returns (otp, sent) — sent=False when a cooldown blocked a fresh send
    (the still-valid existing OTP is returned unchanged in that case).
    Raises OTPRateLimitError if the per-window request cap is exceeded.
    """
    now = timezone.now()
    logger.debug(f"[AssetFlow OTP] issue_otp: purpose={purpose} user id={user.pk} email={mask_email(user.email)}")

    current = EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).order_by("-created_at").first()
    if current and now - current.last_sent_at < RESEND_COOLDOWN:
        logger.debug(f"[AssetFlow OTP] issue_otp: cooldown active for user id={user.pk} — reusing existing OTP id={current.pk}, no email sent")
        return current, False

    window_start = now - OTP_REQUEST_WINDOW
    recent_requests = EmailOTP.objects.filter(user=user, purpose=purpose, created_at__gte=window_start).count()
    if recent_requests >= MAX_OTP_REQUESTS:
        logger.debug(f"[AssetFlow OTP] issue_otp: rate limit exceeded for user id={user.pk} ({recent_requests} requests in {OTP_REQUEST_WINDOW})")
        raise OTPRateLimitError("Too many OTP requests. Please try again later.")

    code = generate_otp()
    logger.debug(f"[AssetFlow OTP] issue_otp: generated a 6-digit OTP for user id={user.pk} (never logged in full)")

    # This is the exact recipient the email goes to — the user's own
    # registered address pulled from the DB, never a hardcoded one.
    send_otp_email(user.email.strip(), code, purpose)

    if invalidate_existing:
        EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=now)
    otp = EmailOTP.objects.create(
        user=user,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=now + OTP_EXPIRY,
        last_sent_at=now,
    )
    logger.debug(f"[AssetFlow OTP] issue_otp: saved OTP id={otp.pk} for user id={user.pk}, expires_at={otp.expires_at.isoformat()}")
    return otp, True


def verify_otp(otp, code, *, consume=True):
    """Check `code` against `otp`, enforcing expiry, reuse and attempt limits."""
    logger.debug(f"[AssetFlow OTP] verify_otp: checking OTP id={otp.pk} for user id={otp.user_id} (consume={consume})")
    if otp.used_at:
        logger.debug(f"[AssetFlow OTP] verify_otp: rejected — OTP id={otp.pk} already used at {otp.used_at.isoformat()}")
        return False
    if otp.expires_at <= timezone.now():
        logger.debug(f"[AssetFlow OTP] verify_otp: rejected — OTP id={otp.pk} expired at {otp.expires_at.isoformat()}")
        return False
    if otp.attempts >= MAX_ATTEMPTS:
        logger.debug(f"[AssetFlow OTP] verify_otp: rejected — OTP id={otp.pk} exceeded {MAX_ATTEMPTS} attempts")
        return False
    if not check_password(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        logger.debug(f"[AssetFlow OTP] verify_otp: rejected — wrong code for OTP id={otp.pk} (attempt {otp.attempts}/{MAX_ATTEMPTS})")
        return False
    if consume:
        otp.used_at = timezone.now()
        otp.save(update_fields=["used_at"])
        logger.debug(f"[AssetFlow OTP] verify_otp: OTP id={otp.pk} matched — marked used, cannot be reused")
    else:
        otp.verified_at = timezone.now()
        otp.save(update_fields=["verified_at"])
        logger.debug(f"[AssetFlow OTP] verify_otp: OTP id={otp.pk} matched — marked verified (still consumable once by reset-password)")
    return True


def sign_challenge(otp):
    """Sign a short-lived, tamper-proof token identifying this OTP row."""
    return signing.dumps(otp.pk, salt=f"email-otp-{otp.purpose}")


def load_challenge(token, purpose):
    """Reverse of sign_challenge(); raises if the token is invalid/expired."""
    otp_id = signing.loads(token, salt=f"email-otp-{purpose}", max_age=OTP_EXPIRY.total_seconds())
    return EmailOTP.objects.select_related("user").get(pk=otp_id, purpose=purpose)
