from django.db import migrations

LEGACY_STATUS = {
    'Pending': 'PENDING',
    'Processing': 'PROCESSING',
    'Shipped': 'SHIPPED',
    'Delivered': 'DELIVERED',
    'Cancelled': 'CANCELLED',
}


def forwards(apps, schema_editor):
    Order = apps.get_model('shop', 'Order')
    for order in Order.objects.select_related('shipping_address'):
        order.status = LEGACY_STATUS.get(order.status, order.status)
        if not order.subtotal:
            order.subtotal = order.total_price
        # Legacy checkout reduced stock when it marked an order paid.
        order.stock_deducted = bool(order.payment_status)
        addr = order.shipping_address
        if addr and not order.delivery_address:
            order.delivery_address = {
                'full_name': addr.full_name,
                'phone': addr.phone,
                'address_line1': addr.address_line1,
                'address_line2': addr.address_line2 or '',
                'city': addr.city,
                'state': addr.state,
                'postal_code': addr.postal_code,
                'country': addr.country,
            }
        order.save(update_fields=['status', 'subtotal', 'stock_deducted', 'delivery_address'])


def backwards(apps, schema_editor):
    Order = apps.get_model('shop', 'Order')
    reverse = {v: k for k, v in LEGACY_STATUS.items()}
    reverse.update({'CONFIRMED': 'Processing', 'OUT_FOR_DELIVERY': 'Shipped'})
    for order in Order.objects.all():
        order.status = reverse.get(order.status, order.status)
        order.save(update_fields=['status'])


class Migration(migrations.Migration):
    dependencies = [('shop', '0005_order_status_payment')]
    operations = [migrations.RunPython(forwards, backwards)]
