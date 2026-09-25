from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class NoLocalSignupAccountAdapter(DefaultAccountAdapter):
    """Close allauth's username/password signup.

    Customers register through /api/accounts/register/, which verifies the
    email with an OTP before activating the account. Social (Google) login
    uses the separate socialaccount adapter and is unaffected.
    """

    def is_open_for_signup(self, request):
        return False


class OpenSocialSignupAdapter(DefaultSocialAccountAdapter):
    """Keep Google sign-up open (the provider has already verified the email)."""

    def is_open_for_signup(self, request, sociallogin):
        return True
