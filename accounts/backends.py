from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q

class EmailOrUsernameModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        try:
            # Check if user exists by username or email (case-insensitive)
            user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
            if user and user.check_password(password):
                return user
        except Exception:
            return None
        return None
