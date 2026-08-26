from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import EmailOTP

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)


class OTPVerifySerializer(serializers.Serializer):
    """Used by POST /api/accounts/verify-login-otp/"""
    challenge_token = serializers.CharField()
    code = serializers.RegexField(r"^\d{6}$")


class ResendOTPSerializer(serializers.Serializer):
    """Used by POST /api/accounts/resend-otp/

    Either `challenge_token` (mid-login OTP) or `email` (forgot-password OTP,
    before any challenge exists) must be provided.
    """
    challenge_token = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False)
    purpose = serializers.ChoiceField(choices=EmailOTP.PURPOSES, required=False)

    def validate(self, attrs):
        if not attrs.get("challenge_token") and not attrs.get("email"):
            raise serializers.ValidationError("Provide either challenge_token or email.")
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    """Used by POST /api/accounts/forgot-password/"""
    email = serializers.EmailField()


class PasswordResetVerifySerializer(serializers.Serializer):
    """Used by POST /api/accounts/verify-forgot-password-otp/"""
    email = serializers.EmailField()
    otp = serializers.RegexField(r"^\d{6}$")


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Used by POST /api/accounts/reset-password/

    reset_token is the short-lived authorization issued by
    verify-forgot-password-otp/ after the OTP was confirmed — the raw OTP
    itself is not resubmitted here.
    """
    email = serializers.EmailField()
    reset_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
