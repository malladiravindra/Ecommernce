from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch
from datetime import timedelta

from .models import EmailOTP

class OTPAuthTests(APITestCase):

    def setUp(self):
        self.register_url = reverse('api_register')
        self.verify_url = reverse('api_verify_otp')
        self.resend_url = reverse('api_resend_otp')

    @patch('accounts.views.send_otp_email')
    def test_registration_flow_success(self, mock_send_email):
        """Test successful registration: unverified user and OTP creation."""
        data = {
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "SecurePassword123!"
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        
        # Check user created and is inactive (unverified)
        user = User.objects.get(email="testuser@example.com")
        self.assertFalse(user.is_active)
        
        # Check OTP record created
        otp_record = EmailOTP.objects.filter(email=user.email).first()
        self.assertIsNotNone(otp_record)
        self.assertEqual(len(otp_record.otp), 6)
        self.assertFalse(otp_record.is_used)
        
        # Verify email utility was called
        mock_send_email.assert_called_once_with(user.email, otp_record.otp)

    @patch('accounts.views.send_otp_email')
    def test_registration_validation_errors(self, mock_send_email):
        """Test registration fails with duplicate emails or bad passwords."""
        # Setup existing user
        User.objects.create_user("existing", "existing@example.com", "Password123!")

        # Duplicate email
        data = {
            "username": "newuser",
            "email": "existing@example.com",
            "password": "Password123!"
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Password too weak (no uppercase, no special chars)
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "password"
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        mock_send_email.assert_not_called()

    def test_otp_verification_success(self):
        """Test successful OTP verification activates the user."""
        user = User.objects.create_user("testuser", "testuser@example.com", "SecurePassword123!", is_active=False)
        otp_record = EmailOTP.objects.create(
            user=user,
            email=user.email,
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        
        data = {
            "email": "testuser@example.com",
            "otp": "123456"
        }
        response = self.client.post(self.verify_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check user is now verified (active)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        
        # Check OTP is marked as used
        otp_record.refresh_from_db()
        self.assertTrue(otp_record.is_used)

    def test_otp_verification_incorrect_code(self):
        """Test incorrect OTP returns a bad request error."""
        user = User.objects.create_user("testuser", "testuser@example.com", "SecurePassword123!", is_active=False)
        EmailOTP.objects.create(
            user=user,
            email=user.email,
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        
        data = {
            "email": "testuser@example.com",
            "otp": "999999"  # Incorrect
        }
        response = self.client.post(self.verify_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_otp_verification_expired(self):
        """Test expired OTP fails verification."""
        user = User.objects.create_user("testuser", "testuser@example.com", "SecurePassword123!", is_active=False)
        EmailOTP.objects.create(
            user=user,
            email=user.email,
            otp="123456",
            created_at=timezone.now() - timedelta(minutes=10),
            expires_at=timezone.now() - timedelta(minutes=5)  # Already expired
        )
        
        data = {
            "email": "testuser@example.com",
            "otp": "123456"
        }
        response = self.client.post(self.verify_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expired", response.data['error'].lower())

    @patch('accounts.views.send_otp_email')
    def test_resend_otp_success(self, mock_send_email):
        """Test resending OTP generates new code, invalidates old, and sends."""
        user = User.objects.create_user("testuser", "testuser@example.com", "SecurePassword123!", is_active=False)
        old_otp = EmailOTP.objects.create(
            user=user,
            email=user.email,
            otp="123456",
            created_at=timezone.now() - timedelta(seconds=70), # Outside rate limit cooldown
            expires_at=timezone.now() + timedelta(minutes=4)
        )
        
        data = {"email": "testuser@example.com"}
        response = self.client.post(self.resend_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify old OTP is invalidated (is_used=True)
        old_otp.refresh_from_db()
        self.assertTrue(old_otp.is_used)
        
        # Verify new OTP created
        new_otp = EmailOTP.objects.filter(email=user.email, is_used=False).first()
        self.assertIsNotNone(new_otp)
        self.assertNotEqual(new_otp.otp, "123456")
        
        # Verify email utility called
        mock_send_email.assert_called_once_with(user.email, new_otp.otp)

    def test_resend_otp_rate_limiting(self):
        """Test resending OTP is rate limited if requested too quickly."""
        user = User.objects.create_user("testuser", "testuser@example.com", "SecurePassword123!", is_active=False)
        EmailOTP.objects.create(
            user=user,
            email=user.email,
            otp="123456",
            created_at=timezone.now() - timedelta(seconds=30), # Within 60 seconds
            expires_at=timezone.now() + timedelta(minutes=4)
        )
        
        data = {"email": "testuser@example.com"}
        response = self.client.post(self.resend_url, data)
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
