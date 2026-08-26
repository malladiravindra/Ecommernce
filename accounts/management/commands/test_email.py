from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a safe SMTP diagnostic email without printing credentials or OTPs."

    def add_arguments(self, parser):
        parser.add_argument("recipient", nargs="?", default=settings.EMAIL_HOST_USER)

    def handle(self, *args, **options):
        recipient = options["recipient"]
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            raise CommandError("EMAIL_HOST_USER and EMAIL_HOST_PASSWORD are required in .env")
        if not recipient:
            raise CommandError("Provide a recipient email address")
        sent = send_mail(
            "AssetFlow SMTP test",
            "This message confirms that AssetFlow Gmail SMTP is configured.",
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(f"SMTP accepted {sent} message(s)."))