import os
import django
import requests
from django.core.files import File
from io import BytesIO

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecommernce.settings')
django.setup()

from shop.models import Category, Product, ProductImage
from django.contrib.auth.models import User

def seed():
    print("Expanding seeded database with required E-Commerce taxonomy...")
    
    # Create Superuser (Developer) if not exists
    if not User.objects.filter(username='developer').exists():
        User.objects.create_superuser('developer', 'developer@example.com', 'devpassword123')
        print("Superuser (Developer) created: developer / devpassword123")
        
    # Create Normal Customer (Client) if not exists
    if not User.objects.filter(username='customer').exists():
        User.objects.create_user('customer', 'customer@example.com', 'customerpassword123')
        print("Normal Customer (Client) created: customer / customerpassword123")
    
    # Specific required Categories for modern E-commerce grid
    categories_data = [
        {"name": "Mobile products", "image_url": "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=500&auto=format&fit=crop"},
        {"name": "Watches", "image_url": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500&auto=format&fit=crop"},
        {"name": "Earphones", "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop"},
        {"name": "Clothes", "image_url": "https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=500&auto=format&fit=crop"}
    ]
    
    cats = {}
    for cat_info in categories_data:
        cat, created = Category.objects.get_or_create(name=cat_info["name"])
        cats[cat_info["name"]] = cat
        if created:
            print(f"Created Category: {cat.name}")
            try:
                response = requests.get(cat_info["image_url"], timeout=10)
                if response.status_code == 200:
                    fp = BytesIO()
                    fp.write(response.content)
                    file_name = f"{cat.slug}.jpg"
                    cat.image.save(file_name, File(fp))
                    cat.save()
            except Exception as e:
                print(f"Error fetching category img for {cat.name}: {e}")

    # Dynamic Inventory Mapped to requirements
    products_data = [
        # Mobiles
        {
            "name": "Vortex Infinity 5G Phone", 
            "category": cats["Mobile products"],
            "price": 999.00, 
            "discount_price": 899.00,
            "featured": True,
            "description": "Edge-to-edge liquid crystal screen with 200MP cinematic optical sensors and all-day quantum batteries.",
            "image_url": "https://images.unsplash.com/photo-1592890288564-76628a30a657?w=800&auto=format&fit=crop",
            "gallery_urls": [
                "https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=800",
                "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=800",
                "https://images.unsplash.com/photo-1580910051074-3eb694886505?w=800"
            ]
        },

        # Earphones
        {
            "name": "Aura Sonic Noise-Canceling Buds", 
            "category": cats["Earphones"],
            "price": 199.00, 
            "discount_price": 175.00,
            "featured": True,
            "description": "Unparalleled acoustics engineered with adaptive spatial active noise suppression and 40 hours reserve.",
            "image_url": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=800&auto=format&fit=crop",
            "gallery_urls": [
                "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800",
                "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=800",
                "https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800"
            ]
        },
        # Clothes
        {
            "name": "Urban Onyx Windbreaker", 
            "category": cats["Clothes"],
            "price": 120.00, 
            "discount_price": 99.00,
            "featured": True,
            "description": "Waterproof matte shield structure built for traversing city environments during intense gales.",
            "image_url": "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=800&auto=format&fit=crop",
            "gallery_urls": [
                "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=800",
                "https://images.unsplash.com/photo-1551488831-00ddcb6c6bd3?w=800",
                "https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=800"
            ]
        }
    ]

    for p_info in products_data:
        prod, created = Product.objects.get_or_create(
            name=p_info["name"],
            category=p_info["category"],
            defaults={
                "price": p_info["price"],
                "discount_price": p_info["discount_price"],
                "featured": p_info["featured"],
                "description": p_info["description"],
                "stock": 20
            }
        )
        if created:
            print(f"Created Product: {prod.name}")
            try:
                response = requests.get(p_info["image_url"], timeout=10)
                if response.status_code == 200:
                    fp = BytesIO()
                    fp.write(response.content)
                    file_name = f"{prod.slug}.jpg"
                    prod.image.save(file_name, File(fp))
                    prod.save()
            except Exception as e:
                print(f"Error downloading photo for {prod.name}: {e}")
                
            # Populate Gallery Images if applicable
            gallery_urls = p_info.get("gallery_urls", [])
            for idx, url in enumerate(gallery_urls):
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        fp = BytesIO()
                        fp.write(response.content)
                        img_obj = ProductImage(product=prod)
                        file_name = f"{prod.slug}_gal_{idx}.jpg"
                        img_obj.image.save(file_name, File(fp), save=True)
                except Exception as e:
                    print(f"Error downloading gallery photo {idx+1} for {prod.name}: {e}")

    print("System catalogue augmentation successfully dispatched!")

if __name__ == '__main__':
    seed()
