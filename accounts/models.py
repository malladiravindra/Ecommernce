from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class EmailOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps', null=True, blank=True)
    email = models.EmailField(db_index=True)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.email} - {self.otp} - Used: {self.is_used}"
