from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

User = get_user_model()


def _extract_otp(email_body):
    # Every OTP email body contains a standalone 6-digit line: "...\n\n123456\n\n..."
    import re
    return re.search(r"\d{6}", email_body).group(0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="admin", email="admin@example.com", password="OldPassword123!"
        )

    def test_login_returns_jwt_pair_directly(self):
        response = self.client.post(
            "/api/accounts/login/",
            {"email": "admin@example.com", "password": "OldPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_forgot_password_delivers_otp_only_to_the_registered_user(self):
        response = self.client.post(
            "/api/accounts/forgot-password/",
            {"email": "admin@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        # The OTP must go to the user's own email — never the SMTP sender account.
        self.assertEqual(mail.outbox[0].to, ["admin@example.com"])
        self.assertNotEqual(mail.outbox[0].to, ["malladiravindra1@gmail.com"])

    def test_unknown_forgot_password_email_returns_same_response_and_sends_verification(self):
        response = self.client.post(
            "/api/accounts/forgot-password/",
            {"email": "unknown@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["unknown@example.com"])

    def test_full_forgot_password_flow_and_otp_cannot_be_reused(self):
        # 1. Request OTP
        request_response = self.client.post(
            "/api/accounts/forgot-password/", {"email": "admin@example.com"}, format="json"
        )
        self.assertEqual(request_response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        code = _extract_otp(mail.outbox[0].body)

        # 2. Wrong OTP is rejected
        wrong = self.client.post(
            "/api/accounts/verify-forgot-password-otp/",
            {"email": "admin@example.com", "otp": "000000"},
            format="json",
        )
        self.assertEqual(wrong.status_code, 400)

        # 3. Correct OTP verifies and returns a reset_token
        verify_response = self.client.post(
            "/api/accounts/verify-forgot-password-otp/",
            {"email": "admin@example.com", "otp": code},
            format="json",
        )
        self.assertEqual(verify_response.status_code, 200)
        self.assertIn("reset_token", verify_response.data)
        self.assertNotIn("otp", verify_response.data)

        # 4. Mismatched passwords are rejected
        mismatch = self.client.post(
            "/api/accounts/reset-password/",
            {
                "email": "admin@example.com",
                "reset_token": verify_response.data["reset_token"],
                "new_password": "NewPassword123!",
                "confirm_password": "Different123!",
            },
            format="json",
        )
        self.assertEqual(mismatch.status_code, 400)

        # 5. Reset succeeds with matching passwords
        reset_response = self.client.post(
            "/api/accounts/reset-password/",
            {
                "email": "admin@example.com",
                "reset_token": verify_response.data["reset_token"],
                "new_password": "NewPassword123!",
                "confirm_password": "NewPassword123!",
            },
            format="json",
        )
        self.assertEqual(reset_response.status_code, 200)
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password("NewPassword123!"))

        # 6. The same reset_token cannot be replayed
        replay = self.client.post(
            "/api/accounts/reset-password/",
            {
                "email": "admin@example.com",
                "reset_token": verify_response.data["reset_token"],
                "new_password": "AnotherPassword123!",
                "confirm_password": "AnotherPassword123!",
            },
            format="json",
        )
        self.assertEqual(replay.status_code, 400)

    def test_resend_otp_respects_cooldown_and_reissues_after_it(self):
        self.client.post("/api/accounts/forgot-password/", {"email": "admin@example.com"}, format="json")
        self.assertEqual(len(mail.outbox), 1)

        # Immediate resend is blocked by the cooldown — no second email.
        cooldown_response = self.client.post(
            "/api/accounts/resend-otp/", {"email": "admin@example.com"}, format="json"
        )
        self.assertEqual(cooldown_response.status_code, 429)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_otp_unknown_email_does_not_reveal_existence(self):
        response = self.client.post(
            "/api/accounts/resend-otp/", {"email": "unknown@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
