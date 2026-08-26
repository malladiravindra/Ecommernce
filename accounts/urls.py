from django.urls import path

from .views import (
    LoginView,
    LogoutView,
    RequestPasswordResetView,
    ResendOTPView,
    ResetPasswordView,
    VerifyForgotPasswordOTPView,
    VerifyLoginOTPView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="accounts_api_login"),
    path("verify-login-otp/", VerifyLoginOTPView.as_view(), name="api_verify_login_otp"),
    path("resend-otp/", ResendOTPView.as_view(), name="api_resend_otp"),
    path("logout/", LogoutView.as_view(), name="api_logout"),

    path("forgot-password/", RequestPasswordResetView.as_view(), name="api_forgot_password"),
    path("verify-forgot-password-otp/", VerifyForgotPasswordOTPView.as_view(), name="api_verify_forgot_password_otp"),
    path("verify-reset-otp/", VerifyForgotPasswordOTPView.as_view(), name="api_verify_reset_otp"),
    path("resend-reset-otp/", ResendOTPView.as_view(), name="api_resend_reset_otp"),
    path("reset-password/", ResetPasswordView.as_view(), name="api_reset_password"),

    # Backward-compatible aliases (safe to remove once nothing calls them).
    path("login/verify-otp/", VerifyLoginOTPView.as_view()),
    path("login/resend-otp/", ResendOTPView.as_view()),
    path("password-reset/request/", RequestPasswordResetView.as_view()),
]
