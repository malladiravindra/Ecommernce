from django.core.mail import send_mail
from django.conf import settings

def send_otp_email(email, otp):
    """
    Sends a 6-digit verification OTP to the user's registered email address.
    """
    subject = "AssetFlow — Verify Your Account"
    message = (
        f"Your AssetFlow verification OTP is: {otp}\n\n"
        f"This OTP expires in 5 minutes. Do NOT share it with anyone.\n\n"
        f"If you did not register for an account, please ignore this email."
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@assetflow.com')
    
    # Send email with fail_silently=False so we catch and log errors
    send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=[email],
        fail_silently=False
    )
