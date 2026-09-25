"""Browser (Selenium) end-to-end checks for the admin panel and customer pages.

Runs against the isolated test database. The Razorpay widget itself needs
real gateway keys and network access, so the gateway leg is covered by the
API tests in test_commerce.py; here the payment step is exercised up to the
server's "gateway not configured" response.
"""
import logging
import os
import re
import tempfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from shop.models import Cart, CartItem, Category, Order, OrderItem, Payment, Product

MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="", MEDIA_ROOT=MEDIA_ROOT,
)
class CommerceUITests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        logging.getLogger('django.server').setLevel(logging.ERROR)
        opts = Options()
        for arg in ("--headless", "--disable-gpu", "--window-size=1400,1000"):
            opts.add_argument(arg)
        opts.set_capability("goog:loggingPrefs", {"browser": "SEVERE"})
        cls.browser = webdriver.Chrome(options=opts)
        cls.browser.implicitly_wait(2)
        cls.image_path = os.path.join(MEDIA_ROOT, "upload.png")
        Image.new("RGB", (40, 40), "blue").save(cls.image_path)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.browser.delete_all_cookies()

    # helpers
    def wait(self, timeout=10):
        return WebDriverWait(self.browser, timeout)

    def go(self, path):
        self.browser.get(self.live_server_url + path)

    def wait_text(self, selector, text, timeout=10):
        self.wait(timeout).until(EC.text_to_be_present_in_element((By.CSS_SELECTOR, selector), text))

    def js_errors(self):
        """Console errors, ignoring missing images/favicons and blocked third-party scripts."""
        return [
            e["message"] for e in self.browser.get_log("browser")
            if not re.search(r"favicon|\.(png|jpg|jpeg|webp|ico)|placeholder\.com|Failed to load resource", e["message"])
        ]

    def click(self, element_id):
        el = self.browser.find_element(By.ID, element_id)
        self.browser.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", el)
        el.click()

    def fill(self, element_id, value):
        el = self.browser.find_element(By.ID, element_id)
        el.clear()
        el.send_keys(value)

    def test_admin_panel_flow(self):
        User.objects.create_user("boss", "boss@example.com", "Adm1n!Pass123", is_staff=True)
        buyer = User.objects.create_user("buyer", "buyer@example.com", "Cust!Pass123")

        # Admin login -> separate admin panel
        self.go("/admin-login/")
        self.fill("admin-email", "boss@example.com")
        self.fill("admin-password", "Adm1n!Pass123")
        self.click("submit-btn")
        self.wait().until(EC.url_contains("/panel/"))
        self.wait_text("#stats", "Total products")

        # Category
        self.go("/panel/categories/")
        self.fill("cat-name", "Audio")
        self.click("cat-save")
        self.wait_text("#rows", "Audio")
        self.assertTrue(Category.objects.filter(name="Audio").exists())

        # Product with image through the form
        self.go("/panel/products/add/")
        self.wait().until(lambda d: len(Select(d.find_element(By.ID, "category")).options) > 1)
        self.fill("name", "Studio Speaker")
        self.fill("brand", "Acme")
        Select(self.browser.find_element(By.ID, "category")).select_by_visible_text("Audio")
        self.fill("description", "Bookshelf speaker")
        self.fill("price", "5000")
        self.fill("discount_price", "4500")
        self.fill("stock", "12")
        self.browser.execute_script("document.getElementById('image').classList.remove('d-none')")
        self.browser.find_element(By.ID, "image").send_keys(self.image_path)
        self.click("save-btn")
        self.wait().until(EC.url_contains("created=1"))
        product = Product.objects.get(name="Studio Speaker")
        self.assertEqual((product.stock, product.price, product.brand), (12, Decimal("5000"), "Acme"))
        self.assertTrue(product.image)

        # Listing + search
        self.go("/panel/products/?q=studio")
        self.wait_text("#rows", "Studio Speaker")

        # Inventory adjust
        self.go("/panel/inventory/")
        form = self.wait().until(EC.presence_of_element_located((By.CSS_SELECTOR, f'[data-stock-form="{product.id}"]')))
        stock_input = form.find_element(By.TAG_NAME, "input")
        stock_input.clear()
        stock_input.send_keys("9")
        form.find_element(By.TAG_NAME, "button").click()
        self.wait_text(".ap-toasts", "set to 9")
        product.refresh_from_db()
        self.assertEqual(product.stock, 9)

        # A paid order (as produced by payment verification) moves through the workflow
        order = Order.objects.create(user=buyer, status=Order.CONFIRMED, payment_status=True, stock_deducted=True,
                                     subtotal=4500, total_price=4500, delivery_address={"full_name": "Buyer", "city": "Pune"})
        OrderItem.objects.create(order=order, product=product, product_name=product.name, price=4500, quantity=1)
        Payment.objects.create(order=order, user=buyer, provider_order_id="order_ui1", provider_payment_id="pay_ui1",
                               amount=4500, status=Payment.SUCCESS)
        self.go(f"/panel/orders/{order.id}/")
        self.wait().until(EC.presence_of_element_located((By.ID, "new-status")))
        Select(self.browser.find_element(By.ID, "new-status")).select_by_value("PROCESSING")
        self.click("status-save")
        self.wait_text("#order-root", "Processing")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PROCESSING)

        self.go("/panel/orders/")
        self.wait_text("#rows", f"#{order.id}")
        self.go("/panel/customers/")
        self.wait_text("#rows", "buyer@example.com")
        self.go("/panel/")
        self.wait_text("#recent-orders", f"#{order.id}")
        self.assertEqual(self.js_errors(), [])

    def test_customer_registration_checkout_and_profile(self):
        category = Category.objects.create(name="Books")
        product = Product.objects.create(category=category, name="Django Guide", description="Book",
                                         price=Decimal("600"), stock=5)

        # Register -> OTP -> login
        self.go("/register/")
        self.fill("reg-fullname", "Asha Rao")
        self.fill("reg-email", "asha@example.com")
        self.fill("reg-password", "Str0ng!Passw0rd")
        self.fill("reg-password2", "Str0ng!Passw0rd")
        self.click("register-submit-btn")
        self.wait().until(EC.url_contains("/verify-otp/"))
        user = User.objects.get(email="asha@example.com")
        self.assertEqual((user.first_name, user.last_name, user.is_active), ("Asha", "Rao", False))
        otp = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group(0)
        for box, digit in zip(self.browser.find_elements(By.CSS_SELECTOR, ".otp-box"), otp):
            box.send_keys(digit)
        self.click("verify-btn")
        self.wait(15).until(EC.url_contains("/login/"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)

        self.fill("login-email", "asha@example.com")
        self.fill("login-password", "Str0ng!Passw0rd")
        self.click("login-submit-btn")
        self.wait().until(lambda d: "/login/" not in d.current_url)

        # Cart (via the existing add-to-cart API from the product page)
        self.go(f"/products/{product.slug}/")
        self.browser.execute_script(
            "return fetch('/api/cart/add/', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json',"
            "'X-CSRFToken': (document.cookie.match(/csrftoken=([^;]+)/)||[])[1]}, body: JSON.stringify({product_id: %d, quantity: 2})})" % product.id
        )
        self.wait().until(lambda d: CartItem.objects.filter(cart__user=user).exists())

        # Address through the API-driven form, then back to checkout
        self.go("/addresses/add/?next=/checkout/")
        for field, value in {"full_name": "Asha Rao", "phone": "9876543210", "address_line1": "1 MG Road",
                             "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001"}.items():
            self.fill(field, value)
        self.click("save-btn")
        self.wait().until(EC.url_contains("/checkout/"))
        self.assertIn("1200", self.browser.find_element(By.ID, "pay-btn").text)

        # Place order -> PENDING order stored; gateway not configured -> clear message, no payment recorded
        self.click("pay-btn")
        self.wait_text("#checkout-alert", "Online payment is not available")
        order = Order.objects.get(user=user)
        self.assertEqual((order.status, order.total_price), (Order.PENDING, Decimal("1200.00")))
        self.assertEqual(order.delivery_address["city"], "Bengaluru")
        self.assertFalse(Payment.objects.exists())
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)  # unpaid orders never touch stock

        # Order history shows the pending order
        self.go(f"/orders/{order.id}/")
        self.assertIn("Awaiting payment", self.browser.page_source)

        # Profile update
        self.go("/profile/")
        self.wait().until(lambda d: d.find_element(By.ID, "full_name").get_attribute("value") == "Asha Rao")
        self.fill("full_name", "Asha K Rao")
        self.fill("phone_number", "9123456789")
        self.click("save-btn")
        self.wait_text("#profile-alert", "Profile updated")
        user.refresh_from_db()
        self.assertEqual(user.last_name, "K Rao")

        # A customer never sees the admin panel
        self.go("/panel/")
        self.assertNotIn("/panel/", self.browser.current_url)
        self.assertEqual(self.js_errors(), [])

    def test_role_separation_in_browser(self):
        from shop.models import Offer
        User.objects.create_user("boss", "boss@example.com", "Adm1n!Pass123", is_staff=True, first_name="Store", last_name="Admin")
        User.objects.create_user("shopper", "shopper@example.com", "Cust!Pass123", first_name="Sam", last_name="Shopper")
        category = Category.objects.create(name="Gadgets")
        product = Product.objects.create(category=category, name="Smart Lamp", description="d", price=Decimal("1000"), stock=4)

        # Admin: one login page, backend decides the destination.
        self.go("/login/")
        self.fill("login-email", "boss@example.com")
        self.fill("login-password", "Adm1n!Pass123")
        self.click("login-submit-btn")
        self.wait().until(EC.url_contains("/panel/"))
        self.wait_text(".ap-sidebar-foot", "You are an Admin")

        self.go("/panel/profile/")
        self.wait_text("#p-role", "ADMIN")
        self.assertEqual(self.browser.find_element(By.ID, "p-type").text, "Administrator")

        # Offer created through the admin UI.
        self.go("/panel/offers/")
        self.wait().until(EC.presence_of_element_located((By.ID, "oc-%d" % category.id)))
        self.click("new-offer")
        self.wait().until(EC.visibility_of_element_located((By.ID, "o-name")))
        self.fill("o-name", "Launch Week")
        self.fill("o-value", "25")
        self.browser.find_element(By.ID, "oc-%d" % category.id).click()
        self.click("o-save")
        self.wait_text("#rows", "Launch Week")
        offer = Offer.objects.get(name="Launch Week")
        self.assertEqual((offer.discount_value, list(offer.categories.all())), (Decimal("25"), [category]))

        # New launch toggled through the admin UI.
        self.go("/panel/new-launches/")
        btn = self.wait().until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'button[data-id="{product.id}"][data-set="true"]')))
        btn.click()
        self.wait_text("#current", "Smart Lamp")
        product.refresh_from_db()
        self.assertTrue(product.is_new_launch)

        self.go("/panel/reports/")
        self.wait_text("#summary", "Revenue")
        self.assertEqual(self.js_errors(), [])

        # Customer: same login page -> store, customer role, no admin controls.
        self.browser.delete_all_cookies()
        self.go("/login/")
        self.fill("login-email", "shopper@example.com")
        self.fill("login-password", "Cust!Pass123")
        self.click("login-submit-btn")
        self.wait().until(lambda d: "/login/" not in d.current_url)
        self.assertNotIn("/panel/", self.browser.current_url)

        self.go("/products/")
        page = self.browser.page_source
        self.assertIn("NEW LAUNCH", page)
        self.assertIn("₹750.00", page)       # 25% offer applied by the backend
        self.assertIn("25% off", page)
        self.assertNotIn("Admin Panel", page)

        self.go("/profile/")
        self.wait_text("#role-badge", "You are a Customer")
        self.assertEqual(self.browser.find_element(By.ID, "role-code").text, "CUSTOMER")
        self.assertEqual(self.browser.find_element(By.ID, "role-type").text, "Customer")

        self.go("/panel/offers/")
        self.assertNotIn("/panel/", self.browser.current_url)
        self.assertEqual(self.js_errors(), [])
