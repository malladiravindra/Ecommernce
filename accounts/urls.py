from django.urls import path
from .views import RegistrationAPIView, VerifyOTPAPIView, ResendOTPAPIView

urlpatterns = [
    path('api/register/', RegistrationAPIView.as_view(), name='api_register'),
    path('api/verify-otp/', VerifyOTPAPIView.as_view(), name='api_verify_otp'),
    path('api/resend-otp/', ResendOTPAPIView.as_view(), name='api_resend_otp'),
]
