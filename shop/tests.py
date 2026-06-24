from django.test import TestCase, Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from django.contrib.auth.models import User
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import json
import logging

class HomePageSeleniumTest(StaticLiveServerTestCase):
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Suppress "Broken pipe" errors from the live server during browser teardown
        logging.getLogger('django.server').setLevel(logging.ERROR)
        
        # Set up headless Chrome options so the test runs in the background
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Initialize the WebDriver (Selenium Manager handles the executable)
        cls.selenium = webdriver.Chrome(options=chrome_options)
        cls.selenium.implicitly_wait(10)
        
    @classmethod
    def tearDownClass(cls):
        cls.selenium.quit()
        super().tearDownClass()
        
    def test_login_page_renders(self):
        # Navigate to the login page
        self.selenium.get(self.live_server_url + "/login/")
        
        # 1. Check Title
        self.assertIn("Shopping_App", self.selenium.title)
        
        # 2. Check if the login form elements are rendered
        self.assertIn("password-input", self.selenium.page_source)
        
        # 3. Check for Sign-in text (supporting both 'Sign-in' and 'Sign in' case-insensitively)
        page_source_lower = self.selenium.page_source.lower()
        self.assertTrue("sign-in" in page_source_lower or "sign in" in page_source_lower)


class PortalLoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create standard customer
        self.customer_user = User.objects.create_user(
            username='customer_test',
            email='customer@example.com',
            password='customerpassword123'
        )
        # Create developer / superuser
        self.developer_user = User.objects.create_superuser(
            username='dev_test',
            email='developer@example.com',
            password='devpassword123'
        )
        
    def test_customer_portal_login_redirects_normal_user_normally(self):
        """Standard customer logs in via customer portal; redirect_url is None or standard."""
        response = self.client.post(
            reverse('api_login'),
            data=json.dumps({
                'email': 'customer@example.com',
                'password': 'customerpassword123'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIsNone(data['redirect_url'])

    def test_customer_portal_login_redirects_developer_to_admin_dashboard(self):
        """Developer logs in via customer portal; redirected automatically to admin dashboard."""
        response = self.client.post(
            reverse('api_login'),
            data=json.dumps({
                'email': 'developer@example.com',
                'password': 'devpassword123'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['redirect_url'], '/admin-dashboard/')

    def test_developer_portal_login_successful_for_developer(self):
        """Developer logs in via developer portal successfully."""
        response = self.client.post(
            reverse('api_admin_login'),
            data=json.dumps({
                'email': 'developer@example.com',
                'password': 'devpassword123'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['redirect_url'], '/admin-dashboard/')

    def test_developer_portal_login_forbidden_for_standard_customer(self):
        """Customer tries to log in via developer portal; access is rejected with a 403."""
        response = self.client.post(
            reverse('api_admin_login'),
            data=json.dumps({
                'email': 'customer@example.com',
                'password': 'customerpassword123'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn("restricted to Developers and Administrators", data['error'])