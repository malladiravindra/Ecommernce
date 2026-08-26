import random
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import EmailOTP
from .serializers import UserRegisterSerializer, VerifyOTPSerializer, ResendOTPSerializer
from .utils import send_otp_email

class RegistrationAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            # Create user (is_active=False by default in serializer)
            user = serializer.save()
            
            # Generate 6-digit OTP
            otp = f"{random.randint(100000, 999999):06d}"
            expires_at = timezone.now() + timedelta(minutes=5)
            
            # Store OTP in database
            EmailOTP.objects.create(
                user=user,
                email=user.email,
                otp=otp,
                expires_at=expires_at
            )
            
            # Send OTP via SMTP
            try:
                send_otp_email(user.email, otp)
            except Exception as e:
                # Rollback user creation if SMTP fails so they can retry registration after fixing config
                user.delete()
                return Response(
                    {"error": f"SMTP Error: Failed to send verification email. Details: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            return Response(
                {"success": True, "message": "Verification OTP sent to your registered email address."},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            
            # Find user
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                return Response(
                    {"error": "User account not found for this email."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Find the latest unused OTP
            latest_otp = EmailOTP.objects.filter(
                email__iexact=email,
                is_used=False
            ).order_by('-created_at').first()
            
            if not latest_otp:
                return Response(
                    {"error": "No active OTP found. Please request a new OTP."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if latest_otp.is_expired():
                return Response(
                    {"error": "OTP has expired. Please request a new one."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if latest_otp.otp != otp:
                return Response(
                    {"error": "Incorrect OTP. Please try again."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Mark OTP as used
            latest_otp.is_used = True
            latest_otp.save()
            
            # Activate user account
            user.is_active = True
            user.save()
            
            return Response(
                {"success": True, "message": "Account verified successfully. You can now log in."},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResendOTPAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = ResendOTPSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            
            # Find user
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                return Response(
                    {"error": "User account not found for this email."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Basic rate limit: block resending if the last OTP was requested less than 60 seconds ago
            last_otp = EmailOTP.objects.filter(email__iexact=email).order_by('-created_at').first()
            if last_otp:
                elapsed = (timezone.now() - last_otp.created_at).total_seconds()
                if elapsed < 60:
                    remaining = int(60 - elapsed)
                    return Response(
                        {"error": f"Please wait {remaining} seconds before resending."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )
            
            # Invalidate all previous unused OTPs
            EmailOTP.objects.filter(email__iexact=email, is_used=False).update(is_used=True)
            
            # Generate new 6-digit OTP
            otp = f"{random.randint(100000, 999999):06d}"
            expires_at = timezone.now() + timedelta(minutes=5)
            
            # Create new OTP entry
            EmailOTP.objects.create(
                user=user,
                email=email,
                otp=otp,
                expires_at=expires_at
            )
            
            # Send via SMTP
            try:
                send_otp_email(email, otp)
            except Exception as e:
                return Response(
                    {"error": f"SMTP Error: Failed to send new OTP. Details: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
            return Response(
                {"success": True, "message": "A new verification OTP has been sent to your registered email."},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
