from django.core.management.base import BaseCommand

from shop.services import expire_pending_orders


class Command(BaseCommand):
    help = "Cancel unpaid PENDING orders older than PENDING_ORDER_TIMEOUT_MINUTES (schedule this, e.g. every 15 minutes)."

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=None, help='Override the timeout for this run.')

    def handle(self, *args, **options):
        count = expire_pending_orders(timeout_minutes=options['minutes'])
        self.stdout.write(self.style.SUCCESS(f"Expired {count} abandoned pending order(s)."))
