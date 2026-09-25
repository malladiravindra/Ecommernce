from django.conf import settings
from django.db import models


class EmailOTP(models.Model):
	LOGIN = "login"
	PASSWORD_RESET = "password_reset"
	REGISTRATION = "registration"
	PURPOSES = ((LOGIN, "Login"), (PASSWORD_RESET, "Password reset"), (REGISTRATION, "Registration"))

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	purpose = models.CharField(max_length=20, choices=PURPOSES)
	code_hash = models.CharField(max_length=128)
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField()
	attempts = models.PositiveSmallIntegerField(default=0)
	verified_at = models.DateTimeField(null=True, blank=True)
	used_at = models.DateTimeField(null=True, blank=True)
	last_sent_at = models.DateTimeField(auto_now_add=True)


class PasswordResetCode(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	code_hash = models.CharField(max_length=128)
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField()
	attempts = models.PositiveSmallIntegerField(default=0)
	used_at = models.DateTimeField(null=True, blank=True)


class CustomerProfile(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
	phone_number = models.CharField(max_length=20, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"Profile of {self.user}"
