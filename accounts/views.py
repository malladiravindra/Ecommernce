import logging
import re

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import EmailOTP
from .serializers import (
    LoginSerializer,
    OTPVerifySerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    ResendOTPSerializer,
)
from .utils import (
    OTPDeliveryError,
    OTPRateLimitError,
    issue_decoy_otp,
    issue_otp,
    load_challenge,
    mask_email,
    sign_challenge,
    verify_otp,
)

logger = logging.getLogger(__name__)

User = get_user_model()


def _create_pending_user(email):
    """Create a new User for `email` with no usable password yet.

    Lets forgot-password double as self-registration for an email with no
    existing account: they finish by verifying the OTP and setting a
    password via reset-password/. Until then set_unusable_password() means
    the account exists but can never be logged into.
    """
    base = re.sub(r"[^\w.@+-]", "", email.split("@", 1)[0]) or "user"
    username = base
    suffix = 1
    while User.objects.filter(username__iexact=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    user = User.objects.create(username=username, email=email, is_active=True)
    user.set_unusable_password()
    user.save(update_fields=["password"])
    logger.debug("forgot-password: created pending account id=%s username=%s for email=%s", user.pk, username, mask_email(email))
    return user

# Shown for forgot-password/resend regardless of whether the email is
# registered, and regardless of whether sending actually happened (rate
# limit, SMTP hiccup, etc.) — never reveal account existence or delivery
# state to the client.
GENERIC_RESET_MESSAGE = "If that email is registered, a reset code has been sent."


def token_response(user):
    refresh = TokenObtainPairSerializer.get_token(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class LoginView(APIView):
    """POST /api/accounts/login/

    Validates credentials and, on success, returns JWT access/refresh
    tokens directly — no OTP step. (OTP is only used by the separate
    forgot-password flow; see RequestPasswordResetView below.)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data={
            "identifier": request.data.get("identifier") or request.data.get("email") or request.data.get("username"),
            "password": request.data.get("password"),
        })
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        user_by_email = User.objects.filter(email__iexact=identifier).first()
        user = authenticate(request, username=user_by_email.get_username() if user_by_email else identifier,
                            password=serializer.validated_data["password"])
        if not user or not user.is_active or not user.email:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(token_response(user))


class VerifyLoginOTPView(APIView):
    """POST /api/accounts/verify-login-otp/

    Verifies the OTP tied to challenge_token, consuming it, then issues JWT
    access + refresh tokens.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            otp = load_challenge(serializer.validated_data["challenge_token"], EmailOTP.LOGIN)
        except (signing.BadSignature, signing.SignatureExpired, EmailOTP.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Invalid or expired login challenge."}, status=400)
        if not verify_otp(otp, serializer.validated_data["code"]):
            return Response({"detail": "Invalid or expired verification code."}, status=400)
        return Response(token_response(otp.user))


class ResendOTPView(APIView):
    """POST /api/accounts/resend-otp/

    Generic resend for both flows:
      - mid-login:       {"challenge_token": "..."}
      - forgot-password: {"email": "user@example.com"}

    Invalidates the previous OTP and emails a brand new one to the user's
    own address, subject to a 60s cooldown and a rolling max-requests cap.
    Never reveals whether an email is registered.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        challenge_token = data.get("challenge_token")

        if challenge_token:
            try:
                otp = load_challenge(challenge_token, EmailOTP.LOGIN)
            except (signing.BadSignature, signing.SignatureExpired, EmailOTP.DoesNotExist, ValueError, TypeError):
                return Response({"detail": "Invalid or expired login challenge."}, status=400)
            user, purpose = otp.user, EmailOTP.LOGIN
        else:
            purpose = data.get("purpose") or EmailOTP.PASSWORD_RESET
            user = User.objects.filter(email__iexact=data["email"], is_active=True).first()
            if not user:
                return Response({"detail": GENERIC_RESET_MESSAGE})

        try:
            new_otp, sent = issue_otp(user, purpose)
        except OTPRateLimitError:
            logger.warning("resend-otp: rate limit hit for user id=%s purpose=%s", user.pk, purpose)
            if purpose == EmailOTP.PASSWORD_RESET:
                # Don't reveal rate-limit state for an email-identified
                # request — it would leak account existence.
                return Response({"detail": GENERIC_RESET_MESSAGE})
            return Response({"detail": "Too many OTP requests. Please try again later."}, status=429)
        except OTPDeliveryError as e:
            # Full traceback already logged inside utils.send_otp_email.
            logger.error("resend-otp: OTP delivery failed for user id=%s purpose=%s", user.pk, purpose)
            detail = "Unable to send the verification email. Check SMTP configuration."
            if settings.DEBUG:
                detail = f"SMTP delivery failed: {str(e.__cause__ or e)}. Check settings.py and the server console for full traceback."
            return Response({"detail": detail}, status=503)

        response = {
            "success": sent,
            "detail": "A new code has been sent." if sent else "Please wait before requesting another code.",
            "resend_available_in": 0 if sent else 60,
        }
        if purpose == EmailOTP.LOGIN:
            response["challenge_token"] = sign_challenge(new_otp)
        return Response(response, status=200 if sent else 429)


class RequestPasswordResetView(APIView):
    """POST /api/accounts/forgot-password/

    Body: {"email": "user@example.com"}

    Looks the user up by their submitted email. If found, emails a fresh
    6-digit OTP to that exact address with a 5-minute expiry. If no account
    exists for that email, one is created on the spot (see
    _create_pending_user) with no usable password, and a real OTP is sent
    for it too — verifying it and setting a password via reset-password/
    completes self-registration. The response is identical regardless of
    whether the email was already registered, whether the OTP was
    rate-limited, or whether SMTP delivery failed — none of that is ever
    surfaced to the client. Failures ARE logged server-side (see
    accounts/utils.py) so delivery problems remain debuggable.

    A disabled (is_active=False) account is the one exception: we don't
    silently create a duplicate account or reactivate it — it gets a
    look-alike OTP that can never verify, same as a totally unknown email
    used to.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip()
        logger.debug(f"[ForgotPassword] Step 1: received request for email={mask_email(email)}")

        # Look up the user by the *submitted* email — this is what makes the
        # recipient dynamic instead of hardcoded.
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            if User.objects.filter(email__iexact=email, is_active=False).exists():
                logger.debug(f"[ForgotPassword] Step 2: email={mask_email(email)} belongs to a disabled account — sending look-alike OTP (not stored), not creating a duplicate")
                issue_decoy_otp(email)
            else:
                logger.debug(f"[ForgotPassword] Step 2: no account found for email={mask_email(email)} — creating a new account and sending a real OTP")
                user = _create_pending_user(email)
        if user and user.email:
            logger.debug(f"[ForgotPassword] Step 2: user found — id={user.pk}, registered email={mask_email(user.email)}")
            try:
                issue_otp(user, EmailOTP.PASSWORD_RESET)
            except OTPDeliveryError as e:
                # Logged (with traceback) inside utils.send_otp_email already.
                # The response to the client stays generic on purpose in production,
                # but we surface it in debug mode to facilitate troubleshooting.
                logger.error("forgot-password: OTP delivery failed for user id=%s", user.pk)
                if settings.DEBUG:
                    return Response({
                        "detail": f"SMTP delivery failed: {str(e.__cause__ or e)}. Check settings.py and the server console for full traceback."
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            except OTPRateLimitError:
                logger.warning("forgot-password: rate limit hit for user id=%s", user.pk)
        return Response({"success": True, "detail": GENERIC_RESET_MESSAGE})


class VerifyForgotPasswordOTPView(APIView):
    """POST /api/accounts/verify-forgot-password-otp/

    Body: {"email": "user@example.com", "otp": "123456"}

    Validates the OTP (exists, not expired, not used, under the attempt
    limit) without consuming it, marks it verified, and returns a signed,
    time-limited reset_token — the only authorization reset-password/ needs.
    The OTP itself is never echoed back.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        logger.debug(f"[VerifyForgotPasswordOTP] Step 1: verify request for email={mask_email(email)}")

        otp = EmailOTP.objects.filter(
            user__email__iexact=email,
            purpose=EmailOTP.PASSWORD_RESET,
            used_at__isnull=True,
        ).order_by("-created_at").first()
        if not otp:
            logger.debug(f"[VerifyForgotPasswordOTP] Step 2: no pending password-reset OTP found for email={mask_email(email)}")
            return Response({"detail": "Invalid or expired OTP."}, status=400)
        logger.debug(f"[VerifyForgotPasswordOTP] Step 2: latest pending OTP id={otp.pk} for user id={otp.user_id}")

        if not verify_otp(otp, serializer.validated_data["otp"], consume=False):
            return Response({"detail": "Invalid or expired OTP."}, status=400)

        reset_token = sign_challenge(otp)
        logger.debug(f"[VerifyForgotPasswordOTP] Step 3: OTP id={otp.pk} verified — issuing reset_token for user id={otp.user_id}")
        return Response({
            "success": True,
            "token": reset_token,
            "reset_token": reset_token,
            "detail": "OTP verified. You can now set a new password."
        })


class ResetPasswordView(APIView):
    """POST /api/accounts/reset-password/

    Body: {"email", "reset_token", "new_password", "confirm_password"}

    Requires a reset_token from a successful verify-forgot-password-otp/
    call (so the OTP itself never has to be resubmitted), re-checks it
    hasn't already been used and matches the submitted email, hashes and
    saves the new password via Django's password hashing, then deletes
    every password-reset OTP for that user so nothing can be reused.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        # Support both 'token' (sent by reset_password.html) and 'reset_token' (expected by serializer)
        mutable_data = request.data.copy()
        if "token" in mutable_data and "reset_token" not in mutable_data:
            mutable_data["reset_token"] = mutable_data["token"]

        serializer = PasswordResetConfirmSerializer(data=mutable_data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        logger.debug(f"[ResetPassword] Step 1: reset request for email={mask_email(data['email'])}")

        if data["new_password"] != data["confirm_password"]:
            logger.debug("[ResetPassword] Step 2: rejected — new_password and confirm_password do not match")
            return Response({"detail": "Passwords do not match."}, status=400)

        try:
            otp = load_challenge(data["reset_token"], EmailOTP.PASSWORD_RESET)
        except (signing.BadSignature, signing.SignatureExpired, EmailOTP.DoesNotExist, ValueError, TypeError):
            logger.debug("[ResetPassword] Step 2: rejected — reset_token is invalid or expired")
            return Response({"detail": "Invalid or expired reset token."}, status=400)

        if otp.user.email.lower() != data["email"].strip().lower():
            logger.debug(f"[ResetPassword] Step 2: rejected — reset_token belongs to user id={otp.user_id}, not the submitted email")
            return Response({"detail": "Invalid or expired reset token."}, status=400)
        if not otp.verified_at or otp.used_at:
            logger.debug(f"[ResetPassword] Step 2: rejected — OTP id={otp.pk} was not verified first (or already used)")
            return Response({"detail": "This OTP must be verified first."}, status=400)
        logger.debug(f"[ResetPassword] Step 2: reset_token OK — user id={otp.user_id}, OTP id={otp.pk} verified at {otp.verified_at.isoformat()}")

        try:
            validate_password(data["new_password"], otp.user)
        except ValidationError as error:
            logger.debug(f"[ResetPassword] Step 3: rejected — password failed strength validation: {error.messages}")
            return Response({"detail": error.messages}, status=400)

        otp.user.set_password(data["new_password"])
        otp.user.save(update_fields=["password"])
        logger.debug(f"[ResetPassword] Step 4: password updated for user id={otp.user_id} via set_password() + save()")

        # Invalidate/delete every password-reset OTP for this user so the
        # token and the OTP it came from can never be reused.
        deleted_count, _ = EmailOTP.objects.filter(user=otp.user, purpose=EmailOTP.PASSWORD_RESET).delete()
        logger.debug(f"[ResetPassword] Step 5: invalidated {deleted_count} password-reset OTP row(s) for user id={otp.user_id}")
        return Response({"success": True, "detail": "Password updated successfully."})


class LogoutView(APIView):
    def post(self, request):
        try:
            RefreshToken(request.data["refresh"]).blacklist()
        except (KeyError, ValueError):
            return Response({"detail": "Invalid refresh token."}, status=400)
        return Response(status=status.HTTP_204_NO_CONTENT)
