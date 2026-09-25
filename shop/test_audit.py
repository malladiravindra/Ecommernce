"""Production-readiness audit tests: security, payment idempotency, webhook,
stock concurrency/rollback, expiry, archival, images, snapshots, migrations."""
import hashlib
import hmac
import io
import json
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection, OperationalError
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from shop import services
from shop.models import (
    CartItem, Category, Order, OrderItem, Payment, PaymentWebhookEvent, Product, ProductImage, ShippingAddress,
)
from shop.test_commerce import ADDRESS, TEST_SECRET, CommerceTestBase, png_file, sign

WEBHOOK_SECRET = "whsec_unit"


def webhook_body(event, gateway_order_id, payment_id="pay_WH1", amount=160000, currency="INR", **extra):
    entity = {"id": payment_id, "order_id": gateway_order_id, "amount": amount, "currency": currency, **extra}
    return json.dumps({"event": event, "payload": {"payment": {"entity": entity}}}).encode()


@override_settings(RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
class AuditBase(CommerceTestBase):
    def verify(self, gateway_order_id="order_GW123", payment_id="pay_ABC", api=None):
        return (api or self.cust_api).post("/api/payments/verify/", {
            "razorpay_order_id": gateway_order_id, "razorpay_payment_id": payment_id,
            "razorpay_signature": sign(gateway_order_id, payment_id),
        }, format="json")

    def send_webhook(self, body, event_id="evt_1", signature=None):
        sig = signature if signature is not None else hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.anon_api.generic("POST", "/api/payments/webhook/", body, content_type="application/json",
                                     HTTP_X_RAZORPAY_SIGNATURE=sig, HTTP_X_RAZORPAY_EVENT_ID=event_id)

    def stock(self):
        self.product.refresh_from_db()
        return self.product.stock


# ───────────────────────── Security ─────────────────────────

class CsrfAndLegacyEndpointTests(AuditBase):
    def csrf_client(self, login=None):
        c = Client(enforce_csrf_checks=True)
        if login:
            c.force_login(login)
        return c

    def test_session_api_writes_require_csrf_token(self):
        c = self.csrf_client(self.customer)
        c.get("/addresses/")  # page render sets the csrftoken cookie
        body = json.dumps(ADDRESS)
        self.assertEqual(c.post("/api/addresses/", body, content_type="application/json").status_code, 403)
        token = c.cookies["csrftoken"].value
        self.assertEqual(c.post("/api/addresses/", body, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 201)

    def test_session_login_views_enforce_csrf(self):
        for page, endpoint, email, pw in [("/login/", "/ajax-login/", "cust1@example.com", "Cust!Pass123"),
                                          ("/admin-login/", "/ajax-admin-login/", "admin1@example.com", "Adm1n!Pass123")]:
            c = self.csrf_client()
            body = json.dumps({"email": email, "password": pw})
            self.assertEqual(c.post(endpoint, body, content_type="application/json").status_code, 403, endpoint)
            c.get(page)
            self.assertIn("csrftoken", c.cookies, page)
            r = c.post(endpoint, body, content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
            self.assertEqual(r.status_code, 200, endpoint)

    def test_session_login_is_rate_limited(self):
        c = Client()
        body = json.dumps({"email": "cust1@example.com", "password": "wrong"})
        codes = [c.post("/ajax-login/", body, content_type="application/json").status_code for _ in range(11)]
        self.assertEqual(codes[:10], [400] * 10)
        self.assertEqual(codes[10], 429)

    def test_logout_requires_post_with_csrf(self):
        c = self.csrf_client(self.customer)
        self.assertEqual(c.get("/logout/").status_code, 405)
        self.assertEqual(c.post("/logout/").status_code, 403)
        c.get("/profile/")
        self.assertEqual(c.post("/logout/", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value).status_code, 302)
        self.assertIn(c.get("/api/accounts/profile/").status_code, (401, 403))

    def test_registration_cannot_bypass_email_otp(self):
        Client().post("/register/", {"username": "sneaky", "email": "sneaky@example.com",
                                     "password1": "Str0ng!Passw0rd", "password2": "Str0ng!Passw0rd"})
        Client().post("/accounts/signup/", {"username": "sneaky2", "email": "sneaky2@example.com",
                                            "password1": "Str0ng!Passw0rd", "password2": "Str0ng!Passw0rd"})
        self.assertFalse(User.objects.filter(email__in=["sneaky@example.com", "sneaky2@example.com"]).exists())

    def test_removed_and_duplicate_endpoints_are_gone(self):
        self.client.force_login(self.admin)
        for method, url in [("post", "/api/token/"), ("get", "/user-management/"), ("post", "/checkout/verify/"),
                            ("get", "/api/accounts/users/")]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 404, url)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post("/checkout/", {"address_id": 1}).status_code, 405)  # old server-side checkout

    def test_soap_endpoint_is_read_only_and_safe(self):
        CartItem.objects.all().delete()
        envelope = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
                    f'<addToCart><user_id>{self.customer.id}</user_id><product_id>{self.product.id}</product_id>'
                    '<quantity>3</quantity></addToCart></soapenv:Body></soapenv:Envelope>')
        r = Client().post("/api/soap/", envelope, content_type="text/xml")
        self.assertIn(b"Unsupported SOAP action", r.content)
        self.assertFalse(CartItem.objects.exists())
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
                '<listProducts>&lol2;</listProducts></soapenv:Body></soapenv:Envelope>')
        self.assertIn(b"Invalid or unsafe XML", Client().post("/api/soap/", bomb, content_type="text/xml").content)
        listing = Client().post("/api/soap/", envelope.replace("addToCart", "listProducts"), content_type="text/xml")
        self.assertIn(b"Headphones", listing.content)

    def test_passwords_are_hashed(self):
        self.assertTrue(self.customer.password.startswith(("pbkdf2_", "argon2", "bcrypt")))
        self.assertNotIn("Cust!Pass123", self.customer.password)

    def test_auth_failures_return_proper_status(self):
        r = self.anon_api.post("/api/accounts/login/", {"email": "cust1@example.com", "password": "nope"}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.anon_api.get("/api/orders/").status_code, 401)
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION="Bearer not.a.token")
        self.assertEqual(bad.get("/api/orders/").status_code, 401)


class AdminPermissionMatrixTests(AuditBase):
    ADMIN_GETS = ["/api/admin/dashboard/", "/api/admin/products/", "/api/admin/categories/", "/api/admin/customers/",
                  "/api/admin/orders/"]

    def test_every_admin_api_by_role(self):
        superuser = User.objects.create_superuser("root", "root@example.com", "R00t!Pass123")
        roles = {"anon": self.anon_api, "customer": self.cust_api, "staff": self.admin_api, "superuser": APIClient()}
        roles["superuser"].force_authenticate(superuser)
        urls = self.ADMIN_GETS + [f"/api/admin/products/{self.product.id}/", f"/api/admin/customers/{self.customer.id}/"]
        for name, api in roles.items():
            for url in urls:
                code = api.get(url).status_code
                if name == "anon":
                    self.assertIn(code, (401, 403), url)
                elif name == "customer":
                    self.assertEqual(code, 403, url)
                else:
                    self.assertEqual(code, 200, f"{name} {url}")

    def test_panel_pages_blocked_for_customers(self):
        self.client.force_login(self.customer)
        for url in ["/panel/", "/panel/products/", "/panel/orders/", "/panel/customers/", "/panel/inventory/"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertNotIn("/panel/", r["Location"])

    def test_django_admin_cannot_edit_payment_status(self):
        superuser = User.objects.create_superuser("root", "root@example.com", "R00t!Pass123")
        order = Order.objects.create(user=self.customer, total_price=10, status=Order.PENDING)
        payment = Payment.objects.create(order=order, user=self.customer, provider_order_id="order_x", amount=10)
        self.client.force_login(superuser)
        r = self.client.post(f"/admin/shop/payment/{payment.id}/change/", {"status": "SUCCESS"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/admin/shop/payment/add/").status_code, 403)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.PENDING)
        # Normal product management in Django admin still works.
        self.assertEqual(self.client.get(f"/admin/shop/product/{self.product.id}/change/").status_code, 200)


# ───────────────────────── Payments ─────────────────────────

class PaymentIdempotencyTests(AuditBase):
    def test_repeated_verification_is_idempotent(self):
        order = self.place_order(quantity=2)
        self.create_payment(order["id"])
        codes = [self.verify().status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 200])
        self.assertEqual(self.stock(), 8)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Order.objects.get().status, Order.CONFIRMED)

    def test_second_payment_for_confirmed_order_does_not_cancel_it(self):
        order = self.place_order(quantity=2)
        self.create_payment(order["id"], gateway_id="order_A")
        self.assertEqual(self.verify("order_A", "pay_A").status_code, 200)
        # A second window left open and also paid:
        Payment.objects.create(order_id=order["id"], user=self.customer, provider_order_id="order_B", amount=Decimal("1600.00"))
        r = self.verify("order_B", "pay_B")
        self.assertEqual(r.status_code, 409)
        o = Order.objects.get()
        self.assertEqual(o.status, Order.CONFIRMED)
        self.assertEqual(self.stock(), 8)
        dup = Payment.objects.get(provider_order_id="order_B")
        self.assertEqual((dup.status, dup.refund_status), (Payment.SUCCESS, Payment.REFUND_REQUIRED))
        self.assertEqual(Payment.objects.get(provider_order_id="order_A").refund_status, Payment.REFUND_NONE)

    def test_frontend_cannot_change_amount(self):
        self.add_to_cart(quantity=1)
        address_id = self.add_address()
        r = self.cust_api.post("/api/orders/", {"address_id": address_id, "total_price": "1.00", "subtotal": "1", "discount": "999"}, format="json")
        self.assertEqual(Decimal(r.data["order"]["total_price"]), Decimal("800.00"))
        with mock.patch("shop.payments.create_gateway_order", return_value="order_M") as gw:
            self.cust_api.post("/api/payments/create/", {"order_id": r.data["order"]["id"], "amount": 100}, format="json")
        self.assertEqual(gw.call_args[0][0], 80000)
        self.assertEqual(Payment.objects.get().amount, Decimal("800.00"))

    def test_tampered_payment_amount_is_never_confirmed(self):
        order = self.place_order(quantity=1)
        self.create_payment(order["id"])
        Payment.objects.update(amount=Decimal("1.00"))
        self.assertEqual(self.verify().status_code, 409)
        self.assertEqual(Order.objects.get().status, Order.PENDING)
        self.assertEqual(self.stock(), 10)

    def test_retry_after_failed_and_closed_window(self):
        order = self.place_order(quantity=1)
        self.create_payment(order["id"], gateway_id="order_try1")
        # Attempt 1 fails at the gateway (webhook), window closed.
        self.send_webhook(webhook_body("payment.failed", "order_try1", error_description="Card declined"), "evt_f")
        self.assertEqual(Payment.objects.get(provider_order_id="order_try1").status, Payment.FAILED)
        self.assertEqual(Order.objects.get().status, Order.PENDING)
        # Customer returns and retries from the order page.
        r, _ = self.create_payment(order["id"], gateway_id="order_try2")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.verify("order_try2", "pay_2").status_code, 200)
        self.assertEqual(Order.objects.get().status, Order.CONFIRMED)
        self.assertEqual(self.stock(), 9)
        # A new payment can't be started for an order that's no longer pending.
        r, gw = self.create_payment(order["id"], gateway_id="order_try3")
        self.assertEqual(r.status_code, 400)
        gw.assert_not_called()


class WebhookTests(AuditBase):
    def setUp(self):
        super().setUp()
        self.order = self.place_order(quantity=2)
        self.create_payment(self.order["id"])

    def test_captured_webhook_confirms_order_once(self):
        body = webhook_body("payment.captured", "order_GW123")
        r = self.send_webhook(body, "evt_A")
        self.assertEqual((r.status_code, r.data["status"]), (200, "confirmed"))
        self.assertEqual(self.stock(), 8)
        self.assertEqual(self.send_webhook(body, "evt_A").data["status"], "duplicate_event")  # redelivery
        self.assertEqual(self.send_webhook(webhook_body("order.paid", "order_GW123"), "evt_B").data["status"], "already_processed")
        self.assertEqual(self.verify(payment_id="pay_WH1").status_code, 200)  # browser arrives last
        self.assertEqual(self.stock(), 8)
        self.assertEqual(Payment.objects.get().status, Payment.SUCCESS)
        self.assertEqual(Order.objects.get().status, Order.CONFIRMED)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 2)

    def test_browser_then_webhook_deducts_once(self):
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.send_webhook(webhook_body("payment.captured", "order_GW123", "pay_ABC"), "evt_C").data["status"], "already_processed")
        self.assertEqual(self.stock(), 8)

    def test_invalid_signature_and_mismatched_amount_rejected(self):
        body = webhook_body("payment.captured", "order_GW123")
        self.assertEqual(self.send_webhook(body, signature="forged").status_code, 400)
        self.assertEqual(self.send_webhook(body, signature="").status_code, 400)
        r = self.send_webhook(webhook_body("payment.captured", "order_GW123", amount=100), "evt_D")
        self.assertEqual(r.data["status"], "rejected_amount_mismatch")
        self.assertEqual(Order.objects.get().status, Order.PENDING)
        self.assertEqual(self.stock(), 10)
        with self.settings(RAZORPAY_WEBHOOK_SECRET=""):
            self.assertEqual(self.send_webhook(body, "evt_E").status_code, 400)

    def test_failed_event_never_overrides_success(self):
        self.verify()
        self.send_webhook(webhook_body("payment.failed", "order_GW123"), "evt_F")
        self.assertEqual(Payment.objects.get().status, Payment.SUCCESS)

    def test_refund_is_only_marked_on_razorpay_confirmation(self):
        self.verify()
        self.admin_api.put(f"/api/admin/orders/{self.order['id']}/status/", {"status": "CANCELLED"}, format="json")
        p = Payment.objects.get()
        self.assertEqual((p.status, p.refund_status), (Payment.SUCCESS, Payment.REFUND_REQUIRED))
        refund = json.dumps({"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_1", "payment_id": "pay_ABC"}}}}).encode()
        self.assertEqual(self.send_webhook(refund, "evt_R").data["status"], "refund_processed")
        p.refresh_from_db()
        self.assertEqual((p.status, p.refund_status), (Payment.REFUNDED, Payment.REFUND_PROCESSED))


class ExpiryTests(AuditBase):
    def age(self, order_id, minutes):
        Order.objects.filter(pk=order_id).update(created_at=timezone.now() - timedelta(minutes=minutes))

    def test_abandoned_orders_expire_safely(self):
        stale = self.place_order(quantity=1)
        self.age(stale["id"], 120)
        fresh = Order.objects.create(user=self.other, total_price=10, status=Order.PENDING)
        paying = Order.objects.create(user=self.other, total_price=10, status=Order.PENDING)
        self.age(paying.id, 120)
        Payment.objects.create(order=paying, user=self.other, provider_order_id="order_recent", amount=10)
        call_command("expire_pending_orders", "--minutes", "60", stdout=io.StringIO())
        self.assertEqual(Order.objects.get(pk=stale["id"]).status, Order.CANCELLED)
        self.assertIn("Expired", Order.objects.get(pk=stale["id"]).cancellation_reason)
        self.assertEqual(Order.objects.get(pk=fresh.id).status, Order.PENDING)
        self.assertEqual(Order.objects.get(pk=paying.id).status, Order.PENDING)
        self.assertEqual(self.stock(), 10)  # nothing to restock

    def test_payment_after_expiry_is_recorded_for_refund(self):
        order = self.place_order(quantity=1)
        self.create_payment(order["id"])
        Payment.objects.update(created_at=timezone.now() - timedelta(hours=3))
        self.age(order["id"], 180)
        self.assertEqual(services.expire_pending_orders(60), 1)
        self.assertEqual(Payment.objects.get().status, Payment.FAILED)
        self.assertEqual(self.send_webhook(webhook_body("payment.captured", "order_GW123", amount=80000), "evt_late").data["status"], "refund_required")
        p, o = Payment.objects.get(), Order.objects.get()
        self.assertEqual((p.status, p.refund_status, o.status), (Payment.SUCCESS, Payment.REFUND_REQUIRED, Order.CANCELLED))
        self.assertEqual(self.stock(), 10)


# ───────────────────────── Stock & orders ─────────────────────────

class StockTests(AuditBase):
    def test_last_unit_can_only_be_sold_once(self):
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        a = self.place_order(quantity=1)
        self.other_api.post("/api/cart/add/", {"product_id": self.product.id, "quantity": 1}, format="json")
        b = self.other_api.post("/api/orders/", {"address_id": self.add_address(api=self.other_api)}, format="json").data["order"]
        self.create_payment(a["id"], gateway_id="order_A")
        with mock.patch("shop.payments.create_gateway_order", return_value="order_B"):
            self.other_api.post("/api/payments/create/", {"order_id": b["id"]}, format="json")
        self.assertEqual(self.verify("order_A", "pay_A").status_code, 200)
        self.assertEqual(self.verify("order_B", "pay_B", api=self.other_api).status_code, 409)
        self.assertEqual(self.stock(), 0)
        self.assertEqual(Order.objects.get(pk=b["id"]).status, Order.CANCELLED)
        self.assertEqual(Payment.objects.get(provider_order_id="order_B").refund_status, Payment.REFUND_REQUIRED)

    def test_cancellation_restock_rules(self):
        unpaid = self.place_order(quantity=2)
        self.admin_api.put(f"/api/admin/orders/{unpaid['id']}/status/", {"status": "CANCELLED"}, format="json")
        self.assertEqual(self.stock(), 10)  # unpaid never took stock -> nothing restored
        CartItem.objects.all().delete()
        paid = self.place_order(quantity=3)
        self.create_payment(paid["id"], gateway_id="order_P")
        self.verify("order_P", "pay_P")
        self.assertEqual(self.stock(), 7)
        url = f"/api/admin/orders/{paid['id']}/status/"
        self.assertEqual(self.admin_api.put(url, {"status": "CANCELLED"}, format="json").status_code, 200)
        self.assertEqual(self.admin_api.put(url, {"status": "CANCELLED"}, format="json").status_code, 400)
        self.assertEqual(self.stock(), 10)
        self.assertFalse(Order.objects.get(pk=paid["id"]).stock_deducted)

    def test_illegal_transitions_rejected(self):
        delivered = Order.objects.create(user=self.customer, total_price=10, status=Order.DELIVERED)
        cancelled = Order.objects.create(user=self.customer, total_price=10, status=Order.CANCELLED)
        for order, targets in [(delivered, ["PENDING", "PROCESSING", "CANCELLED", "SHIPPED"]),
                               (cancelled, ["SHIPPED", "DELIVERED", "PENDING", "CONFIRMED"])]:
            for target in targets:
                r = self.admin_api.put(f"/api/admin/orders/{order.id}/status/", {"status": target}, format="json")
                self.assertEqual(r.status_code, 400, (order.status, target))
            order.refresh_from_db()
        self.assertEqual(Order.objects.get(pk=delivered.id).status, Order.DELIVERED)
        self.assertEqual(Order.objects.get(pk=cancelled.id).status, Order.CANCELLED)

    def test_cart_rejects_inactive_out_of_stock_and_bad_actions(self):
        self.add_to_cart(quantity=1)
        item = CartItem.objects.get()
        self.assertEqual(self.cust_api.post("/api/cart/update/", {"item_id": item.id, "action": "explode"}, format="json").status_code, 400)
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        self.assertEqual(self.add_to_cart(quantity=1).status_code, 404)
        self.assertEqual(self.cust_api.post("/api/cart/update/", {"item_id": item.id, "action": "increase"}, format="json").status_code, 400)
        Product.objects.filter(pk=self.product.pk).update(is_active=True, stock=0)
        self.assertEqual(self.add_to_cart(quantity=1).status_code, 400)
        r = self.cust_api.post("/api/orders/", {"address_id": self.add_address()}, format="json")
        self.assertEqual(r.status_code, 400)


class HistoryPreservationTests(AuditBase):
    def test_order_address_snapshot_survives_address_changes(self):
        order = self.place_order(quantity=1)
        address = ShippingAddress.objects.get(user=self.customer)
        self.cust_api.patch(f"/api/addresses/{address.id}/", {"city": "Chennai", "address_line1": "99 New Road"}, format="json")
        snap = self.cust_api.get(f"/api/orders/{order['id']}/").data["delivery_address"]
        self.assertEqual((snap["city"], snap["address_line1"]), ("Hyderabad", "12 Test Street"))
        self.cust_api.delete(f"/api/addresses/{address.id}/")
        self.assertEqual(self.cust_api.get(f"/api/orders/{order['id']}/").data["delivery_address"]["city"], "Hyderabad")

    def test_product_with_orders_is_archived_not_deleted(self):
        order = self.place_order(quantity=1)
        r = self.admin_api.delete(f"/api/admin/products/{self.product.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["archived"])
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        item = OrderItem.objects.get(order_id=order["id"])
        self.assertEqual((item.product_id, item.product_name, item.price), (self.product.id, "Headphones", Decimal("800.00")))
        self.assertEqual(self.anon_api.get("/api/products/").data, [])
        # A product nobody ordered is really deleted.
        spare = Product.objects.create(category=self.category, name="Spare", description="d", price=5, stock=1)
        self.assertEqual(self.admin_api.delete(f"/api/admin/products/{spare.id}/").status_code, 204)
        self.assertFalse(Product.objects.filter(pk=spare.id).exists())

    def test_category_with_products_is_protected_at_db_level(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.category.delete()


class ImageTests(AuditBase):
    def upload(self, **files):
        data = {"name": "Img", "description": "d", "category": self.category.id, "price": "10", "stock": 1, **files}
        return self.admin_api.post("/api/admin/products/", data, format="multipart")

    def test_image_type_and_size_validation(self):
        png = png_file("x.png").read()
        self.assertEqual(self.upload(image=SimpleUploadedFile("evil.html", png, content_type="text/html")).status_code, 400)
        self.assertEqual(self.upload(image=SimpleUploadedFile("fake.png", b"<script>alert(1)</script>", content_type="image/png")).status_code, 400)
        with mock.patch("shop.serializers.MAX_IMAGE_BYTES", 10):
            self.assertEqual(self.upload(image=png_file("big.png")).status_code, 400)
        bad_gallery = self.upload(images=[png_file("ok.png"), SimpleUploadedFile("g.svg", b"<svg/>", content_type="image/svg+xml")])
        self.assertEqual(bad_gallery.status_code, 400)
        self.assertFalse(Product.objects.filter(name="Img").exists())  # rolled back, nothing half-saved

    def test_upload_urls_and_gallery_delete(self):
        r = self.upload(image=png_file("main.png"), images=[png_file("g1.png")])
        self.assertEqual(r.status_code, 201)
        self.assertIn("/media/products/", r.data["image"])
        image_id = r.data["images"][0]["id"]
        self.assertEqual(self.admin_api.delete(f"/api/admin/products/{r.data['id']}/images/{image_id}/").status_code, 204)
        self.assertFalse(ProductImage.objects.filter(pk=image_id).exists())
        public = self.anon_api.get(f"/api/products/{r.data['id']}/").data
        self.assertTrue(public["image"].startswith("http://testserver/media/"))


# ───────────────────────── Concurrency (real threads) ─────────────────────────

@override_settings(RAZORPAY_KEY_ID="rzp_test_unit", RAZORPAY_KEY_SECRET=TEST_SECRET)
class ConcurrentPurchaseTests(TransactionTestCase):
    """Two buyers pay for the last unit at the same time."""

    def test_last_unit_under_concurrent_verification(self):
        cat = Category.objects.create(name="C")
        product = Product.objects.create(category=cat, name="Last", description="d", price=100, stock=1)
        payments = []
        for i in range(2):
            u = User.objects.create_user(f"buyer{i}", f"b{i}@example.com", "x")
            order = Order.objects.create(user=u, status=Order.PENDING, subtotal=100, total_price=100)
            OrderItem.objects.create(order=order, product=product, product_name="Last", price=100, quantity=1)
            payments.append(Payment.objects.create(order=order, user=u, provider_order_id=f"order_c{i}", amount=100))

        outcomes, barrier = [], threading.Barrier(2)

        def worker(payment):
            barrier.wait()
            for attempt in range(20):  # SQLite serialises writers; retry on "database is locked"
                try:
                    outcomes.append(services.confirm_paid_order(payment, f"pay_{payment.pk}")[1])
                    return
                except OperationalError:
                    import time
                    time.sleep(0.05)
            outcomes.append("error")
            connection.close()

        threads = [threading.Thread(target=worker, args=(p,)) for p in payments]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        product.refresh_from_db()
        self.assertEqual(sorted(outcomes), sorted([services.CONFIRMED, services.REFUND_REQUIRED]), outcomes)
        self.assertEqual(product.stock, 0)
        self.assertEqual(Order.objects.filter(status=Order.CONFIRMED).count(), 1)


# ───────────────────────── Migrations ─────────────────────────

class LegacyOrderMigrationTests(TransactionTestCase):
    before = [("shop", "0004_order_razorpay_order_id")]
    after = [("shop", "0006_migrate_legacy_orders")]

    def tearDown(self):
        # Always leave the schema fully migrated for the tests that run next.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_legacy_orders_convert_without_data_loss(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        user = old.get_model("auth", "User").objects.create(username="legacy", email="legacy@example.com")
        addr = old.get_model("shop", "ShippingAddress").objects.create(
            user_id=user.id, full_name="Legacy", address_line1="1 Old St", city="Delhi", state="DL",
            postal_code="110001", country="India", phone="9999999999")
        OldOrder = old.get_model("shop", "Order")
        paid = OldOrder.objects.create(user_id=user.id, shipping_address_id=addr.id, status="Processing",
                                       total_price=Decimal("500.00"), payment_status=True)
        unpaid = OldOrder.objects.create(user_id=user.id, shipping_address_id=addr.id, status="Pending",
                                         total_price=Decimal("50.00"), payment_status=False)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps.get_model("shop", "Order")
        p, u = new.objects.get(pk=paid.pk), new.objects.get(pk=unpaid.pk)
        self.assertEqual((p.status, p.stock_deducted, p.subtotal, p.total_price), ("PROCESSING", True, Decimal("500.00"), Decimal("500.00")))
        # The remaining migrations must also apply cleanly on top of converted data.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(new.objects.count(), 2)
        self.assertEqual((u.status, u.stock_deducted), ("PENDING", False))
        self.assertEqual(p.delivery_address["city"], "Delhi")
        self.assertEqual(new.objects.count(), 2)
