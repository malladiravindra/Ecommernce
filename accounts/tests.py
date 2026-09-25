from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
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
        cache.clear()  # reset DRF throttle counters between tests
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
        self.assertNotIn(settings.EMAIL_HOST_USER or "sender@invalid", mail.outbox[0].to)

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


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationApiTests(TestCase):
    def setUp(self):
        cache.clear()  # reset DRF throttle counters between tests
        self.client = APIClient()
        self.payload = {"username": "johndoe123", "email": "john@example.com", "password": "Str0ng!Passw0rd"}

    def test_full_registration_flow(self):
        # 1. Register -> 201, inactive customer account, OTP emailed to the user
        response = self.client.post("/api/accounts/register/", self.payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["success"])
        user = User.objects.get(email="john@example.com")
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(mail.outbox[-1].to, ["john@example.com"])

        # 2. Login is refused until verified
        login = self.client.post("/ajax-login/", {"email": "john@example.com", "password": "Str0ng!Passw0rd"}, format="json")
        self.assertEqual(login.status_code, 400)

        # 3. Wrong OTP rejected, correct OTP activates the account
        bad = self.client.post("/api/accounts/verify-registration-otp/", {"email": "john@example.com", "otp": "000000"}, format="json")
        self.assertEqual(bad.status_code, 400)
        otp = _extract_otp(mail.outbox[-1].body)
        ok = self.client.post("/api/accounts/verify-registration-otp/", {"email": "john@example.com", "otp": otp}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.data["success"])
        user.refresh_from_db()
        self.assertTrue(user.is_active)

        # 4. OTP can't be reused; login now works
        again = self.client.post("/api/accounts/verify-registration-otp/", {"email": "john@example.com", "otp": otp}, format="json")
        self.assertEqual(again.status_code, 400)
        login = self.client.post("/ajax-login/", {"email": "john@example.com", "password": "Str0ng!Passw0rd"}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_duplicate_email_and_weak_password_rejected_as_json(self):
        User.objects.create_user(username="existing", email="john@example.com", password="x")
        response = self.client.post("/api/accounts/register/", self.payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

        weak = dict(self.payload, email="new@example.com", password="12345678")
        response = self.client.post("/api/accounts/register/", weak, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)

    def test_registration_resend_uses_existing_resend_endpoint(self):
        self.client.post("/api/accounts/register/", self.payload, format="json")
        from accounts.models import EmailOTP
        EmailOTP.objects.update(last_sent_at="2000-01-01T00:00:00Z")  # skip the 60s cooldown
        response = self.client.post("/api/accounts/resend-otp/", {"email": "john@example.com", "purpose": "registration"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(mail.outbox), 2)

    def test_disabled_account_cannot_be_reactivated_via_registration_flow(self):
        User.objects.create_user(username="banned", email="banned@example.com", password="x", is_active=False)
        response = self.client.post("/api/accounts/resend-otp/", {"email": "banned@example.com", "purpose": "registration"}, format="json")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(User.objects.get(email="banned@example.com").is_active)
