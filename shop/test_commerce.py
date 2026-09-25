"""End-to-end API tests for the admin + customer commerce flows."""
import hashlib
import hmac
import io
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import CustomerProfile
from shop.models import Cart, CartItem, Category, Order, Payment, Product, ShippingAddress

TEST_KEY_ID = "rzp_test_unit"
TEST_SECRET = "unit_test_secret"
MEDIA_ROOT = tempfile.mkdtemp()


def sign(order_id, payment_id, secret=TEST_SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def png_file(name="p.png"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


ADDRESS = {
    "full_name": "Test Customer", "phone": "9876543210", "address_line1": "12 Test Street",
    "city": "Hyderabad", "state": "Telangana", "postal_code": "500001", "country": "India",
}


@override_settings(RAZORPAY_KEY_ID=TEST_KEY_ID, RAZORPAY_KEY_SECRET=TEST_SECRET,
                   DELIVERY_CHARGE="0", FREE_DELIVERY_MIN_ORDER="0", MEDIA_ROOT=MEDIA_ROOT)
class CommerceTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("admin1", "admin1@example.com", "Adm1n!Pass123", is_staff=True)
        self.customer = User.objects.create_user("cust1", "cust1@example.com", "Cust!Pass123")
        self.other = User.objects.create_user("cust2", "cust2@example.com", "Cust!Pass123")
        self.category = Category.objects.create(name="Electronics")
        self.product = Product.objects.create(
            category=self.category, name="Headphones", description="Wireless", price=Decimal("1000.00"),
            discount_price=Decimal("800.00"), stock=10, is_active=True,
        )
        self.admin_api = APIClient()
        self.admin_api.force_authenticate(self.admin)
        self.cust_api = APIClient()
        self.cust_api.force_authenticate(self.customer)
        self.other_api = APIClient()
        self.other_api.force_authenticate(self.other)
        self.anon_api = APIClient()

    # helpers
    def add_address(self, api=None, **overrides):
        r = (api or self.cust_api).post("/api/addresses/", {**ADDRESS, **overrides}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def add_to_cart(self, product=None, quantity=2, api=None):
        return (api or self.cust_api).post("/api/cart/add/", {"product_id": (product or self.product).id, "quantity": quantity}, format="json")

    def place_order(self, quantity=2):
        self.assertEqual(self.add_to_cart(quantity=quantity).status_code, 200)
        r = self.cust_api.post("/api/orders/", {"address_id": self.add_address()}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["order"]

    def create_payment(self, order_id, gateway_id="order_GW123"):
        with mock.patch("shop.payments.create_gateway_order", return_value=gateway_id) as gw:
            r = self.cust_api.post("/api/payments/create/", {"order_id": order_id}, format="json")
        return r, gw


class AuthAndRoleTests(CommerceTestBase):
    def test_admin_and_customer_jwt_login(self):
        admin_tokens = self.anon_api.post("/api/accounts/login/", {"email": "admin1@example.com", "password": "Adm1n!Pass123"}, format="json")
        self.assertEqual(admin_tokens.status_code, 200)
        jwt_admin = APIClient()
        jwt_admin.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_tokens.data['access']}")
        self.assertEqual(jwt_admin.get("/api/admin/dashboard/").status_code, 200)

        cust_tokens = self.anon_api.post("/api/accounts/login/", {"email": "cust1@example.com", "password": "Cust!Pass123"}, format="json")
        self.assertEqual(cust_tokens.status_code, 200)
        jwt_cust = APIClient()
        jwt_cust.credentials(HTTP_AUTHORIZATION=f"Bearer {cust_tokens.data['access']}")
        self.assertEqual(jwt_cust.get("/api/orders/").status_code, 200)
        self.assertEqual(jwt_cust.get("/api/admin/dashboard/").status_code, 403)

    def test_customer_is_blocked_from_every_admin_api(self):
        order = Order.objects.create(user=self.other, total_price=10, status=Order.CONFIRMED)
        calls = [
            ("get", "/api/admin/dashboard/", None),
            ("get", "/api/admin/products/", None),
            ("post", "/api/admin/products/", {"name": "X", "description": "d", "category": self.category.id, "price": "1", "stock": 1}),
            ("patch", f"/api/admin/products/{self.product.id}/", {"price": "1"}),
            ("delete", f"/api/admin/products/{self.product.id}/", None),
            ("post", "/api/admin/categories/", {"name": "Hack"}),
            ("get", "/api/admin/customers/", None),
            ("get", "/api/admin/orders/", None),
            ("get", f"/api/admin/orders/{order.id}/", None),
            ("put", f"/api/admin/orders/{order.id}/status/", {"status": "PROCESSING"}),
        ]
        for method, url, data in calls:
            r = getattr(self.cust_api, method)(url, data, format="json")
            self.assertEqual(r.status_code, 403, f"{method} {url} -> {r.status_code}")
            r = getattr(self.anon_api, method)(url, data, format="json")
            self.assertIn(r.status_code, (401, 403), f"anon {method} {url}")
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("1000.00"))
        self.assertEqual(order.status, Order.CONFIRMED)

    def test_customer_cannot_escalate_via_user_management(self):
        c = self.client
        c.login(username="cust1", password="Cust!Pass123")
        c.post("/user-management/", {"user_id": self.customer.id, "action": "make_superadmin"},
               content_type="application/json", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_superuser or self.customer.is_staff)

    def test_admin_panel_pages_are_admin_only(self):
        self.assertRedirects(self.client.get("/panel/"), "/admin-login/?next=/panel/", fetch_redirect_response=False)
        self.client.login(username="cust1", password="Cust!Pass123")
        self.assertEqual(self.client.get("/panel/products/").status_code, 302)
        self.client.login(username="admin1", password="Adm1n!Pass123")
        for url in ["/panel/", "/panel/products/", "/panel/products/add/", f"/panel/products/{self.product.id}/edit/",
                    "/panel/categories/", "/panel/customers/", "/panel/orders/", "/panel/orders/1/", "/panel/inventory/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_there_is_no_admin_endpoint_to_create_customers(self):
        r = self.admin_api.post("/api/admin/customers/", {"username": "x", "email": "x@example.com"}, format="json")
        self.assertEqual(r.status_code, 405)


class AdminCatalogTests(CommerceTestBase):
    def test_admin_creates_product_with_images_and_customers_see_it(self):
        r = self.admin_api.post("/api/admin/products/", {
            "name": "Smart Watch", "description": "Fitness watch", "category": self.category.id, "brand": "Acme",
            "price": "2500.00", "discount_price": "2000.00", "stock": 7, "is_active": "true",
            "image": png_file("main.png"), "images": [png_file("g1.png"), png_file("g2.png")],
        }, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        product = Product.objects.get(pk=r.data["id"])
        self.assertEqual(product.brand, "Acme")
        self.assertTrue(product.image)
        self.assertEqual(product.images.count(), 2)

        public = self.anon_api.get("/api/products/?q=smart")
        self.assertEqual([p["name"] for p in public.data], ["Smart Watch"])
        self.assertTrue(public.data[0]["in_stock"])

    def test_product_validation(self):
        base = {"name": "Bad", "description": "d", "category": self.category.id, "stock": 1}
        self.assertEqual(self.admin_api.post("/api/admin/products/", {**base, "price": "0"}, format="json").status_code, 400)
        r = self.admin_api.post("/api/admin/products/", {**base, "price": "100", "discount_price": "150"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("discount_price", r.data)
        self.assertEqual(self.admin_api.post("/api/admin/products/", {**base, "price": "100", "stock": -1}, format="json").status_code, 400)

    def test_edit_deactivate_filter_and_delete(self):
        url = f"/api/admin/products/{self.product.id}/"
        self.assertEqual(self.admin_api.patch(url, {"stock": 3, "is_active": False}, format="json").status_code, 200)
        self.assertEqual(self.anon_api.get("/api/products/").data, [])  # inactive hidden from customers
        listing = self.admin_api.get("/api/admin/products/?status=inactive&stock=low")
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(self.admin_api.delete(url).status_code, 204)
        self.assertFalse(Product.objects.filter(pk=self.product.id).exists())

    def test_duplicate_product_names_get_unique_slugs(self):
        payload = {"name": "Headphones", "description": "d", "category": self.category.id, "price": "10", "stock": 1}
        r = self.admin_api.post("/api/admin/products/", payload, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertNotEqual(r.data["slug"], self.product.slug)

    def test_categories_crud_and_delete_guard(self):
        r = self.admin_api.post("/api/admin/categories/", {"name": "Books", "description": "All books"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.admin_api.post("/api/admin/categories/", {"name": "books"}, format="json").status_code, 400)
        self.assertEqual(self.admin_api.patch(f"/api/admin/categories/{r.data['id']}/", {"name": "Novels"}, format="json").data["slug"], "novels")
        blocked = self.admin_api.delete(f"/api/admin/categories/{self.category.id}/")
        self.assertEqual(blocked.status_code, 409)
        self.assertTrue(Product.objects.filter(pk=self.product.id).exists())
        self.assertEqual(self.admin_api.delete(f"/api/admin/categories/{r.data['id']}/").status_code, 204)

    def test_customers_listing_hides_admins_and_secrets(self):
        r = self.admin_api.get("/api/admin/customers/")
        emails = {c["email"] for c in r.data["results"]}
        self.assertEqual(emails, {"cust1@example.com", "cust2@example.com"})
        self.assertNotIn("password", r.data["results"][0])


class CustomerCheckoutTests(CommerceTestBase):
    def test_public_product_search_filter_sort(self):
        Product.objects.create(category=self.category, name="Cable", description="USB", price=Decimal("50"), stock=0)
        names = [p["name"] for p in self.anon_api.get("/api/products/?sort=price_low").data]
        self.assertEqual(names, ["Cable", "Headphones"])
        self.assertEqual(len(self.anon_api.get("/api/products/?in_stock=1").data), 1)
        self.assertEqual(len(self.anon_api.get(f"/api/products/?category={self.category.slug}").data), 2)

    def test_cart_respects_stock_and_never_reduces_it(self):
        self.assertEqual(self.add_to_cart(quantity=4).status_code, 200)
        self.assertEqual(self.add_to_cart(quantity=7).status_code, 400)  # 4 + 7 > 10
        self.assertEqual(self.add_to_cart(quantity=0).status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        item = CartItem.objects.get(cart__user=self.customer)
        r = self.cust_api.post("/api/cart/update/", {"item_id": item.id, "action": "decrease"}, format="json")
        self.assertEqual(r.data["cart_count"], 3)
        r = self.other_api.post("/api/cart/update/", {"item_id": item.id, "action": "remove"}, format="json")
        self.assertEqual(r.status_code, 404)  # can't touch someone else's cart

    def test_address_crud_validation_and_ownership(self):
        self.assertEqual(self.cust_api.post("/api/addresses/", {**ADDRESS, "phone": "abc"}, format="json").status_code, 400)
        self.assertEqual(self.cust_api.post("/api/addresses/", {**ADDRESS, "city": "  "}, format="json").status_code, 400)
        address_id = self.add_address()
        self.assertEqual(self.cust_api.patch(f"/api/addresses/{address_id}/", {"city": "Pune"}, format="json").data["city"], "Pune")
        self.assertEqual(self.other_api.get(f"/api/addresses/{address_id}/").status_code, 404)
        self.assertEqual(self.other_api.delete(f"/api/addresses/{address_id}/").status_code, 404)
        self.assertEqual(self.other_api.get("/api/addresses/").data, [])
        self.assertEqual(self.cust_api.delete(f"/api/addresses/{address_id}/").status_code, 204)

    def test_order_validation(self):
        address_id = self.add_address()
        self.assertEqual(self.cust_api.post("/api/orders/", {"address_id": address_id}, format="json").status_code, 400)  # empty cart
        self.add_to_cart(quantity=3)
        self.assertEqual(self.other_api.post("/api/orders/", {"address_id": address_id}, format="json").status_code, 404)  # not their address

        Product.objects.filter(pk=self.product.pk).update(stock=2)
        r = self.cust_api.post("/api/orders/", {"address_id": address_id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("left in stock", " ".join(r.data["problems"]))

        Product.objects.filter(pk=self.product.pk).update(stock=10, is_active=False)
        self.assertEqual(self.cust_api.post("/api/orders/", {"address_id": address_id}, format="json").status_code, 400)

        Product.objects.filter(pk=self.product.pk).update(is_active=True)
        incomplete = ShippingAddress.objects.create(user=self.customer, full_name="X", address_line1="a", city="c", state="s", postal_code="1234", phone="")
        r = self.cust_api.post("/api/orders/", {"address_id": incomplete.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_totals_and_delivery_charge(self):
        with self.settings(DELIVERY_CHARGE="49", FREE_DELIVERY_MIN_ORDER="5000"):
            order = self.place_order(quantity=2)
        self.assertEqual(Decimal(order["subtotal"]), Decimal("2000.00"))
        self.assertEqual(Decimal(order["discount"]), Decimal("400.00"))
        self.assertEqual(Decimal(order["delivery_charge"]), Decimal("49.00"))
        self.assertEqual(Decimal(order["total_price"]), Decimal("1649.00"))
        self.assertEqual(order["status"], Order.PENDING)
        self.assertEqual(order["delivery_address"]["city"], "Hyderabad")

    def test_full_paid_order_flow_updates_inventory(self):
        order = self.place_order(quantity=2)
        r, gw = self.create_payment(order["id"])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(gw.call_args[0][0], 160000)  # server-side total in paise
        payment = Payment.objects.get(provider_order_id="order_GW123")
        self.assertEqual((payment.status, payment.amount), (Payment.PENDING, Decimal("1600.00")))

        r = self.cust_api.post("/api/payments/verify/", {
            "razorpay_order_id": "order_GW123", "razorpay_payment_id": "pay_ABC",
            "razorpay_signature": sign("order_GW123", "pay_ABC"),
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["order"]["status"], Order.CONFIRMED)
        payment.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(payment.status, Payment.SUCCESS)
        self.assertEqual(self.product.stock, 8)
        self.assertFalse(CartItem.objects.filter(cart__user=self.customer).exists())

        # Replaying the verification must not deduct stock twice.
        self.cust_api.post("/api/payments/verify/", {
            "razorpay_order_id": "order_GW123", "razorpay_payment_id": "pay_ABC",
            "razorpay_signature": sign("order_GW123", "pay_ABC"),
        }, format="json")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

        history = self.cust_api.get("/api/orders/").data
        self.assertEqual((history[0]["id"], history[0]["status"], history[0]["payment"]["status"]), (order["id"], "CONFIRMED", "SUCCESS"))
        self.assertEqual(self.other_api.get(f"/api/orders/{order['id']}/").status_code, 404)
        self.assertEqual(self.other_api.get("/api/orders/").data, [])

    def test_invalid_payment_is_rejected(self):
        order = self.place_order()
        self.create_payment(order["id"])
        r = self.cust_api.post("/api/payments/verify/", {
            "razorpay_order_id": "order_GW123", "razorpay_payment_id": "pay_ABC", "razorpay_signature": "forged",
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Payment.objects.get().status, Payment.FAILED)
        self.assertEqual(Order.objects.get().status, Order.PENDING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        # Someone else can't verify this customer's payment even with a valid signature.
        r = self.other_api.post("/api/payments/verify/", {
            "razorpay_order_id": "order_GW123", "razorpay_payment_id": "pay_X", "razorpay_signature": sign("order_GW123", "pay_X"),
        }, format="json")
        self.assertEqual(r.status_code, 404)

    def test_payment_requires_configured_gateway(self):
        order = self.place_order()
        with self.settings(RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET=""):
            r = self.cust_api.post("/api/payments/create/", {"order_id": order["id"]}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(Payment.objects.count(), 0)

    def test_stock_sold_out_during_payment_cancels_and_flags_refund(self):
        order = self.place_order(quantity=2)
        self.create_payment(order["id"])
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        r = self.cust_api.post("/api/payments/verify/", {
            "razorpay_order_id": "order_GW123", "razorpay_payment_id": "pay_ABC",
            "razorpay_signature": sign("order_GW123", "pay_ABC"),
        }, format="json")
        self.assertEqual(r.status_code, 409)
        o = Order.objects.get()
        self.assertEqual(o.status, Order.CANCELLED)
        self.assertIn("refund required", o.cancellation_reason)
        self.assertEqual(Payment.objects.get().status, Payment.SUCCESS)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

    def test_insufficient_stock_blocks_payment_creation(self):
        order = self.place_order(quantity=2)
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        r, gw = self.create_payment(order["id"])
        self.assertEqual(r.status_code, 409)
        gw.assert_not_called()


class AdminOrderManagementTests(CommerceTestBase):
    def paid_order(self, quantity=2):
        order = self.place_order(quantity=quantity)
        self.create_payment(order["id"])
        self.cust_api.post("/api/payments/verify/", {
            "razorpay_order_id": "order_GW123", "razorpay_payment_id": "pay_ABC",
            "razorpay_signature": sign("order_GW123", "pay_ABC"),
        }, format="json")
        return Order.objects.get(pk=order["id"])

    def set_status(self, order, status, **extra):
        return self.admin_api.put(f"/api/admin/orders/{order.id}/status/", {"status": status, **extra}, format="json")

    def test_status_workflow_to_delivered(self):
        order = self.paid_order()
        for status in ["PROCESSING", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"]:
            r = self.set_status(order, status, tracking_number="AWB123" if status == "SHIPPED" else "")
            self.assertEqual(r.status_code, 200, (status, r.data))
            self.assertEqual(r.data["status"], status)
        self.assertEqual(self.cust_api.get(f"/api/orders/{order.id}/").data["status"], "DELIVERED")
        self.assertEqual(self.cust_api.get(f"/api/orders/{order.id}/").data["tracking_number"], "AWB123")
        self.assertEqual(self.set_status(order, "CANCELLED").status_code, 400)  # terminal

    def test_invalid_transitions_rejected(self):
        pending = self.place_order()
        pending_obj = Order.objects.get(pk=pending["id"])
        self.assertEqual(self.set_status(pending_obj, "CONFIRMED").status_code, 400)  # only payment confirms
        self.assertEqual(self.set_status(pending_obj, "SHIPPED").status_code, 400)
        self.assertEqual(self.set_status(pending_obj, "BOGUS").status_code, 400)

    def test_cancelling_confirmed_order_restocks(self):
        order = self.paid_order(quantity=3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)
        r = self.set_status(order, "CANCELLED", reason="Customer request")
        self.assertEqual(r.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertIn("Refund required", r.data["cancellation_reason"])
        self.assertEqual(Payment.objects.get().status, Payment.SUCCESS)  # admin can't alter payments

    def test_admin_order_listing_and_search(self):
        order = self.paid_order()
        r = self.admin_api.get("/api/admin/orders/?status=CONFIRMED")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["customer"]["email"], "cust1@example.com")
        self.assertEqual(self.admin_api.get(f"/api/admin/orders/?q=%23{order.id}").data["count"], 1)
        detail = self.admin_api.get(f"/api/admin/orders/{order.id}/").data
        self.assertEqual(detail["allowed_transitions"], ["PROCESSING", "CANCELLED"])

    def test_dashboard_reflects_database(self):
        Product.objects.create(category=self.category, name="Old", description="d", price=10, stock=0, is_active=False)
        self.paid_order(quantity=2)  # stock 10 -> 8, total 1600
        Order.objects.create(user=self.other, total_price=50, status=Order.PENDING)
        stats = self.admin_api.get("/api/admin/dashboard/").data["stats"]
        self.assertEqual(stats["total_products"], 2)
        self.assertEqual(stats["active_products"], 1)
        self.assertEqual(stats["out_of_stock_products"], 1)
        self.assertEqual(stats["total_customers"], 2)
        self.assertEqual(stats["total_orders"], 2)
        self.assertEqual(stats["pending_orders"], 1)
        self.assertEqual(stats["delivered_orders"], 0)
        self.assertEqual(Decimal(stats["total_sales"]), Decimal("1600.00"))


class ProfileTests(CommerceTestBase):
    def test_profile_view_and_update(self):
        r = self.cust_api.put("/api/accounts/profile/", {"full_name": "Jane Q Doe", "email": "cust1@example.com", "phone_number": "98765 43210"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.customer.refresh_from_db()
        self.assertEqual((self.customer.first_name, self.customer.last_name), ("Jane", "Q Doe"))
        self.assertEqual(CustomerProfile.objects.get(user=self.customer).phone_number, "9876543210")

    def test_email_change_requires_password_and_uniqueness(self):
        url = "/api/accounts/profile/"
        self.assertEqual(self.cust_api.patch(url, {"email": "new@example.com"}, format="json").status_code, 400)
        self.assertEqual(self.cust_api.patch(url, {"email": "cust2@example.com", "current_password": "Cust!Pass123"}, format="json").status_code, 400)
        r = self.cust_api.patch(url, {"email": "new@example.com", "current_password": "Cust!Pass123"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["email"], "new@example.com")
        self.assertEqual(self.anon_api.get(url).status_code, 401)


class CustomerPagesTests(CommerceTestBase):
    """Every customer page renders from real DB data; owner-only where relevant."""

    def test_customer_pages_render(self):
        order = self.place_order(quantity=1)
        self.add_to_cart(quantity=1)  # checkout needs a non-empty cart
        self.client.login(username="cust1", password="Cust!Pass123")
        address = ShippingAddress.objects.filter(user=self.customer).first()
        for url in ["/", "/products/", f"/products/{self.product.slug}/", "/cart/", "/checkout/", "/orders/",
                    f"/orders/{order['id']}/", f"/orders/{order['id']}/confirmation/", "/profile/", "/addresses/",
                    "/addresses/add/", f"/addresses/{address.id}/edit/", "/dashboard/"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertContains(self.client.get(f"/orders/{order['id']}/"), "Awaiting payment")

    def test_other_customers_pages_and_inactive_products_are_hidden(self):
        order = self.place_order(quantity=1)
        self.client.login(username="cust2", password="Cust!Pass123")
        self.assertEqual(self.client.get(f"/orders/{order['id']}/").status_code, 404)
        self.assertEqual(self.client.get(f"/orders/{order['id']}/confirmation/").status_code, 404)
        address = ShippingAddress.objects.filter(user=self.customer).first()
        self.assertEqual(self.client.get(f"/addresses/{address.id}/edit/").status_code, 404)
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        self.assertEqual(self.client.get(f"/products/{self.product.slug}/").status_code, 404)

    def test_address_form_ignores_offsite_next(self):
        self.client.login(username="cust1", password="Cust!Pass123")
        r = self.client.get("/addresses/add/?next=javascript:alert(1)")
        self.assertNotContains(r, "javascript:alert")
        r = self.client.get("/addresses/add/?next=//evil.example.com/")
        self.assertNotContains(r, "evil.example.com")
