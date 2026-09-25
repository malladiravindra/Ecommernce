from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import CustomerProfile, EmailOTP

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """Used by POST /api/accounts/register/

    Creates an inactive, customer-role account (is_staff/is_superuser are
    never accepted from the client). It becomes active only after the
    emailed registration OTP is verified.
    """
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "full_name"]

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def validate(self, attrs):
        candidate = User(username=attrs.get("username"), email=attrs.get("email"))
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": list(error.messages)})
        return attrs

    def create(self, validated_data):
        first_name, last_name = split_full_name(validated_data.get("full_name", ""))
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=first_name,
            last_name=last_name,
            is_active=False,
        )
        CustomerProfile.objects.create(user=user)
        return user


def split_full_name(full_name):
    parts = (full_name or "").strip().split(None, 1)
    return (parts[0][:150] if parts else ""), (parts[1][:150] if len(parts) > 1 else "")


class ProfileSerializer(serializers.Serializer):
    """Used by GET/PUT/PATCH /api/profile/ — the signed-in user's own profile.

    Changing the email (the login identity) requires the current password.
    """
    username = serializers.CharField(read_only=True)
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    date_joined = serializers.DateTimeField(read_only=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def to_representation(self, user):
        from shop.rbac import get_account_type
        profile, _ = CustomerProfile.objects.get_or_create(user=user)
        role, account_type = get_account_type(user)
        return {
            "username": user.username,
            "full_name": user.get_full_name(),
            "email": user.email,
            "phone_number": profile.phone_number,
            "date_joined": user.date_joined,
            # Server-derived and read-only (never accepted as input).
            "role": role,
            "account_type": account_type,
        }

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Full name is required.")
        return value

    def validate_phone_number(self, value):
        import re
        value = re.sub(r"[\s\-()]", "", value or "")
        if value and not re.fullmatch(r"\+?\d{7,15}", value):
            raise serializers.ValidationError("Enter a valid phone number (7-15 digits).")
        return value

    def validate(self, attrs):
        user = self.instance
        email = attrs.get("email")
        if email is not None:
            email = email.strip().lower()
            attrs["email"] = email
            if email != (user.email or "").lower():
                if not user.check_password(attrs.get("current_password") or ""):
                    raise serializers.ValidationError({"current_password": "Enter your current password to change your email."})
                if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                    raise serializers.ValidationError({"email": "An account with this email already exists."})
        return attrs

    def update(self, user, validated_data):
        if "full_name" in validated_data:
            user.first_name, user.last_name = split_full_name(validated_data["full_name"])
        if "email" in validated_data:
            user.email = validated_data["email"]
        user.save(update_fields=["first_name", "last_name", "email"])
        if "phone_number" in validated_data:
            profile, _ = CustomerProfile.objects.get_or_create(user=user)
            profile.phone_number = validated_data["phone_number"]
            profile.save(update_fields=["phone_number", "updated_at"])
        return user


class RegistrationOTPVerifySerializer(serializers.Serializer):
    """Used by POST /api/accounts/verify-registration-otp/"""
    email = serializers.EmailField()
    otp = serializers.RegexField(r"^\d{6}$")


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
