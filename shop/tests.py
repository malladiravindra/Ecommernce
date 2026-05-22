from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

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
        # Looking for 'password-input' ID which is clearly in the DOM
        self.assertIn("password-input", self.selenium.page_source)
