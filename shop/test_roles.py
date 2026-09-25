"""Role separation (admin vs customer) on one deployment, offers and new launches."""
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from shop.models import CartItem, Offer, Order, OrderItem, Payment, Product
from shop.test_commerce import CommerceTestBase


class RolePermissionMatrixTests(CommerceTestBase):
    """Anonymous / customer / admin against every protected endpoint."""

    def setUp(self):
        super().setUp()
        self.offer = Offer.objects.create(name="Diwali", discount_type=Offer.PERCENT, discount_value=10)
        self.offer.categories.add(self.category)
        self.other_order = Order.objects.create(user=self.other, total_price=10, status=Order.CONFIRMED)

    def test_admin_api_matrix(self):
        gets = ["/api/admin/dashboard/", "/api/admin/products/", "/api/admin/categories/", "/api/admin/customers/",
                "/api/admin/orders/", "/api/admin/offers/", f"/api/admin/offers/{self.offer.id}/",
                "/api/admin/payments/", "/api/admin/reports/", f"/api/admin/orders/{self.other_order.id}/"]
        for url in gets:
            self.assertIn(self.anon_api.get(url).status_code, (401, 403), f"anon {url}")
            self.assertEqual(self.cust_api.get(url).status_code, 403, f"customer {url}")
            self.assertEqual(self.admin_api.get(url).status_code, 200, f"admin {url}")

    def test_customer_cannot_perform_admin_writes(self):
        writes = [
            ("post", "/api/admin/products/", {"name": "X", "description": "d", "category": self.category.id, "price": "5", "stock": 1}),
            ("patch", f"/api/admin/products/{self.product.id}/", {"price": "1"}),
            ("patch", f"/api/admin/products/{self.product.id}/", {"stock": 999}),
            ("patch", f"/api/admin/products/{self.product.id}/", {"is_new_launch": True}),
            ("delete", f"/api/admin/products/{self.product.id}/", None),
            ("post", "/api/admin/offers/", {"name": "Hack", "discount_value": "50", "categories": [self.category.id]}),
            ("patch", f"/api/admin/offers/{self.offer.id}/", {"discount_value": "90"}),
            ("delete", f"/api/admin/offers/{self.offer.id}/", None),
            ("post", "/api/admin/categories/", {"name": "Hack"}),
            ("put", f"/api/admin/orders/{self.other_order.id}/status/", {"status": "PROCESSING"}),
        ]
        for method, url, data in writes:
            self.assertEqual(getattr(self.cust_api, method)(url, data, format="json").status_code, 403, f"{method} {url}")
            self.assertIn(getattr(self.anon_api, method)(url, data, format="json").status_code, (401, 403), f"anon {method} {url}")
        self.product.refresh_from_db()
        self.offer.refresh_from_db()
        self.assertEqual((self.product.price, self.product.stock, self.product.is_new_launch), (Decimal("1000.00"), 10, False))
        self.assertEqual(self.offer.discount_value, Decimal("10.00"))
        self.assertEqual(Order.objects.get(pk=self.other_order.pk).status, Order.CONFIRMED)

    def test_admin_writes_succeed(self):
        r = self.admin_api.post("/api/admin/products/", {"name": "Launch Phone", "description": "d", "category": self.category.id,
                                                         "price": "999", "stock": 5, "is_new_launch": True}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Product.objects.get(pk=r.data["id"]).is_new_launch)
        self.assertEqual(self.admin_api.patch(f"/api/admin/products/{self.product.id}/", {"stock": 3}, format="json").status_code, 200)
        r = self.admin_api.post("/api/admin/offers/", {"name": "Sale", "discount_type": "FLAT", "discount_value": "100",
                                                       "products": [self.product.id]}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.admin_api.patch(f"/api/admin/offers/{r.data['id']}/", {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(self.admin_api.delete(f"/api/admin/offers/{r.data['id']}/").status_code, 204)

    def test_superuser_is_admin_too(self):
        root = User.objects.create_superuser("root", "root@example.com", "R00t!Pass123")
        api = APIClient()
        api.force_authenticate(root)
        self.assertEqual(api.get("/api/admin/reports/").status_code, 200)

    def test_customer_functionality_allowed(self):
        self.assertEqual(self.cust_api.get("/api/products/").status_code, 200)
        self.assertEqual(self.cust_api.get(f"/api/products/{self.product.id}/").status_code, 200)
        self.assertEqual(self.add_to_cart(quantity=1).status_code, 200)
        self.assertEqual(self.cust_api.get("/api/cart/").status_code, 200)
        self.assertEqual(self.cust_api.get("/api/orders/").status_code, 200)
        self.assertEqual(self.cust_api.get("/api/accounts/profile/").status_code, 200)
        self.assertEqual(self.cust_api.get("/api/offers/").status_code, 200)
        # Admins keep full customer functionality as well.
        self.assertEqual(self.add_to_cart(quantity=1, api=self.admin_api).status_code, 200)

    def test_anonymous_limited_to_public(self):
        self.assertEqual(self.anon_api.get("/api/products/").status_code, 200)
        self.assertEqual(self.anon_api.get("/api/offers/").status_code, 200)
        for url in ["/api/cart/", "/api/orders/", "/api/addresses/", "/api/accounts/profile/"]:
            self.assertIn(self.anon_api.get(url).status_code, (401, 403), url)
        self.assertIn(self.anon_api.post("/api/cart/add/", {"product_id": self.product.id}, format="json").status_code, (401, 403))

    def test_public_offer_endpoint_is_read_only(self):
        self.assertEqual(self.cust_api.post("/api/offers/", {"name": "x"}, format="json").status_code, 405)
        self.assertEqual(self.admin_api.post("/api/offers/", {"name": "x"}, format="json").status_code, 405)

    def test_payments_api_is_read_only(self):
        self.assertEqual(self.admin_api.post("/api/admin/payments/", {}, format="json").status_code, 405)


class OwnershipTests(CommerceTestBase):
    def test_client_supplied_user_ids_are_ignored(self):
        mine = self.place_order(quantity=1)
        theirs = Order.objects.create(user=self.other, total_price=10, status=Order.CONFIRMED)
        ids = [o["id"] for o in self.cust_api.get(f"/api/orders/?user_id={self.other.id}&user={self.other.id}").data]
        self.assertEqual(ids, [mine["id"]])
        self.assertEqual(self.cust_api.get(f"/api/orders/{theirs.id}/?user_id={self.other.id}").status_code, 404)
        # Cart add with someone else's id still goes to the requester's cart.
        self.cust_api.post("/api/cart/add/", {"product_id": self.product.id, "quantity": 1, "user_id": self.other.id, "user": self.other.id}, format="json")
        self.assertFalse(CartItem.objects.filter(cart__user=self.other).exists())
        # Address create can't be assigned to another user.
        r = self.cust_api.post("/api/addresses/", {"full_name": "A", "phone": "9876543210", "address_line1": "x", "city": "c",
                                                   "state": "s", "postal_code": "12345", "user": self.other.id}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.other_api.get("/api/addresses/").data, [])

    def test_customer_cannot_see_others_payments(self):
        order = Order.objects.create(user=self.other, total_price=10, status=Order.PENDING)
        Payment.objects.create(order=order, user=self.other, provider_order_id="order_theirs", amount=10)
        r = self.cust_api.post("/api/payments/verify/", {"razorpay_order_id": "order_theirs", "razorpay_payment_id": "p",
                                                         "razorpay_signature": "x"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.cust_api.post("/api/payments/create/", {"order_id": order.id}, format="json").status_code, 404)


class RoleResponseTests(CommerceTestBase):
    def test_jwt_login_returns_backend_role(self):
        for email, pw, role, kind in [("admin1@example.com", "Adm1n!Pass123", "admin", "Administrator"),
                                      ("cust1@example.com", "Cust!Pass123", "customer", "Customer")]:
            r = self.anon_api.post("/api/accounts/login/", {"email": email, "password": pw}, format="json")
            self.assertEqual(r.status_code, 200)
            self.assertEqual((r.data["user"]["role"], r.data["user"]["account_type"], r.data["user"]["email"]), (role, kind, email))
            body = json.dumps(r.data).lower()
            self.assertNotIn("password", body)
            self.assertNotIn("pbkdf2", body)

    def test_session_login_redirects_by_role(self):
        for email, pw, role, redirect in [("admin1@example.com", "Adm1n!Pass123", "admin", "/panel/"),
                                          ("cust1@example.com", "Cust!Pass123", "customer", None)]:
            r = Client().post("/ajax-login/", json.dumps({"email": email, "password": pw}), content_type="application/json")
            data = r.json()
            self.assertEqual((data["user"]["role"], data["redirect_url"]), (role, redirect))
            self.assertNotIn("password", json.dumps(data).lower())

    def test_profile_role_is_server_derived_and_not_writable(self):
        p = self.cust_api.get("/api/accounts/profile/").data
        self.assertEqual((p["role"], p["account_type"]), ("customer", "Customer"))
        self.cust_api.put("/api/accounts/profile/", {"full_name": "Cust One", "email": "cust1@example.com",
                                                    "role": "admin", "account_type": "Administrator", "is_staff": True}, format="json")
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff or self.customer.is_superuser)
        self.assertEqual(self.cust_api.get("/api/accounts/profile/").data["role"], "customer")
        self.assertEqual(self.admin_api.get("/api/accounts/profile/").data["role"], "admin")

    def test_pages_show_the_right_role(self):
        self.client.force_login(self.customer)
        home = self.client.get("/").content.decode()
        self.assertIn("You are a Customer", home)
        self.assertNotIn("Admin Panel", home)
        self.assertIn("You are a Customer", self.client.get("/dashboard/").content.decode())
        for url in ["/panel/", "/panel/offers/", "/panel/new-launches/", "/panel/payments/", "/panel/reports/", "/panel/profile/"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.client.force_login(self.admin)
        home = self.client.get("/").content.decode()
        self.assertIn("You are an Admin", home)
        self.assertIn("Admin Panel", home)
        for url in ["/panel/", "/panel/offers/", "/panel/new-launches/", "/panel/payments/", "/panel/reports/", "/panel/profile/"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIn("You are an Admin", r.content.decode(), url)
        self.client.logout()
        self.assertRedirects(self.client.get("/panel/offers/"), "/admin-login/?next=/panel/offers/", fetch_redirect_response=False)


class OfferPricingTests(CommerceTestBase):
    """Product: price 1000, discount_price 800."""

    def make_offer(self, **kw):
        targets = {"categories": kw.pop("categories", None), "products": kw.pop("products", None)}
        offer = Offer.objects.create(**{"name": "Offer", "discount_type": Offer.PERCENT, "discount_value": 30, **kw})
        if targets["categories"]:
            offer.categories.set(targets["categories"])
        if targets["products"]:
            offer.products.set(targets["products"])
        return offer

    def test_best_price_no_stacking(self):
        self.make_offer(discount_value=10, categories=[self.category])  # 900 > 800 discount price
        self.assertEqual(Product.objects.get(pk=self.product.pk).final_price, Decimal("800.00"))
        self.make_offer(discount_value=30, products=[self.product])   # 700 < 800
        p = self.anon_api.get(f"/api/products/{self.product.id}/").data
        self.assertEqual((Decimal(p["final_price"]), Decimal(p["savings"]), p["offer"]["label"]), (Decimal("700.00"), Decimal("300.00"), "30% off"))

    def test_only_live_offers_apply(self):
        now = timezone.now()
        self.make_offer(discount_value=50, products=[self.product], is_active=False)
        self.make_offer(discount_value=50, products=[self.product], starts_at=now + timedelta(days=1))
        self.make_offer(discount_value=50, products=[self.product], ends_at=now - timedelta(minutes=1))
        self.make_offer(discount_type=Offer.FLAT, discount_value=999.5, products=[self.product])  # would go below ₹1
        self.assertEqual(Product.objects.get(pk=self.product.pk).final_price, Decimal("800.00"))
        # Only the flat offer is live; it just can't apply to this product (would go below the ₹1 floor).
        self.assertEqual([o["discount_type"] for o in self.anon_api.get("/api/offers/").data], ["FLAT"])
        self.assertIsNone(self.anon_api.get("/api/products/").data[0]["offer"])

    def test_offer_price_flows_to_order_and_gateway_and_is_snapshotted(self):
        offer = self.make_offer(discount_value=40, categories=[self.category])  # 600
        order = self.place_order(quantity=2)
        self.assertEqual((Decimal(order["subtotal"]), Decimal(order["discount"]), Decimal(order["total_price"])),
                         (Decimal("2000.00"), Decimal("800.00"), Decimal("1200.00")))
        with mock.patch("shop.payments.create_gateway_order", return_value="order_OFF") as gw:
            self.cust_api.post("/api/payments/create/", {"order_id": order["id"]}, format="json")
        self.assertEqual(gw.call_args[0][0], 120000)
        offer.delete()
        self.assertEqual(OrderItem.objects.get(order_id=order["id"]).price, Decimal("600.00"))
        self.assertEqual(Order.objects.get(pk=order["id"]).total_price, Decimal("1200.00"))

    def test_offer_validation(self):
        base = {"name": "Bad", "categories": [self.category.id]}
        self.assertEqual(self.admin_api.post("/api/admin/offers/", {**base, "discount_value": "100"}, format="json").status_code, 400)
        self.assertEqual(self.admin_api.post("/api/admin/offers/", {**base, "discount_value": "0"}, format="json").status_code, 400)
        self.assertEqual(self.admin_api.post("/api/admin/offers/", {"name": "No target", "discount_value": "10"}, format="json").status_code, 400)
        now = timezone.now()
        r = self.admin_api.post("/api/admin/offers/", {**base, "discount_value": "10", "starts_at": now.isoformat(),
                                                       "ends_at": (now - timedelta(days=1)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_admin_offer_listing_states(self):
        now = timezone.now()
        self.make_offer(name="Live", categories=[self.category])
        self.make_offer(name="Later", categories=[self.category], starts_at=now + timedelta(days=2))
        self.make_offer(name="Old", categories=[self.category], ends_at=now - timedelta(days=1))
        names = lambda state: [o["name"] for o in self.admin_api.get(f"/api/admin/offers/?state={state}").data["results"]]
        self.assertEqual((names("live"), names("scheduled"), names("expired")), (["Live"], ["Later"], ["Old"]))
        self.assertEqual([o["name"] for o in self.anon_api.get("/api/offers/").data], ["Live"])

    def test_storefront_shows_backend_prices_and_badges(self):
        self.make_offer(name="Mega", discount_value=40, products=[self.product])
        Product.objects.filter(pk=self.product.pk).update(is_new_launch=True)
        self.client.force_login(self.customer)
        listing = self.client.get("/products/").content.decode()
        self.assertIn("₹600.00", listing)
        self.assertIn("NEW LAUNCH", listing)
        self.assertIn("40% off", listing)
        detail = self.client.get(f"/products/{self.product.slug}/").content.decode()
        self.assertIn("You save ₹400.00", detail)
        self.assertIn("NEW LAUNCH", self.client.get("/").content.decode())
        self.assertIn("Headphones", self.client.get("/products/?new=1").content.decode())
        Product.objects.filter(pk=self.product.pk).update(is_new_launch=False)
        self.assertNotIn("NEW LAUNCH", self.client.get("/products/").content.decode())


class NewLaunchAndReportTests(CommerceTestBase):
    def test_new_launch_flag_is_admin_controlled(self):
        self.assertEqual(self.anon_api.get("/api/products/?new_launch=1").data, [])
        self.admin_api.patch(f"/api/admin/products/{self.product.id}/", {"is_new_launch": True}, format="json")
        self.assertEqual([p["name"] for p in self.anon_api.get("/api/products/?new_launch=1").data], ["Headphones"])
        self.assertEqual(self.admin_api.get("/api/admin/products/?new_launch=1").data["count"], 1)

    def test_dashboard_reports_and_payments_come_from_db(self):
        order = self.place_order(quantity=2)  # total 1600
        o = Order.objects.get(pk=order["id"])
        o.status, o.payment_status = Order.CONFIRMED, True
        o.save()
        Payment.objects.create(order=o, user=self.customer, provider_order_id="order_R", amount=o.total_price,
                               status=Payment.SUCCESS, refund_status=Payment.REFUND_REQUIRED)
        Offer.objects.create(name="Live", discount_value=5).categories.add(self.category)
        Product.objects.filter(pk=self.product.pk).update(is_new_launch=True)

        stats = self.admin_api.get("/api/admin/dashboard/").data["stats"]
        self.assertEqual((stats["new_launch_products"], stats["active_offers"], stats["refunds_required"]), (1, 1, 1))

        rep = self.admin_api.get("/api/admin/reports/").data
        self.assertEqual((rep["summary"]["paid_orders"], Decimal(rep["summary"]["revenue"]), rep["summary"]["items_sold"]),
                         (1, Decimal("1600.00"), 2))
        self.assertEqual(rep["top_products"][0]["product_name"], "Headphones")
        self.assertEqual(len(rep["daily_sales"]), 1)
        self.assertEqual(self.admin_api.get("/api/admin/reports/?from=2026-02-01&to=2026-01-01").status_code, 400)

        pays = self.admin_api.get("/api/admin/payments/?refund=REQUIRED").data
        self.assertEqual((pays["count"], pays["results"][0]["order_id"], pays["results"][0]["customer_email"]), (1, o.id, "cust1@example.com"))
