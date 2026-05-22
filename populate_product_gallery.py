import os
import django
import requests
from django.core.files import File
from io import BytesIO

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecommernce.settings')
django.setup()

from shop.models import Product, ProductImage

def download_image(url):
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            fp = BytesIO()
            fp.write(response.content)
            return fp
    except Exception as e:
        print(f"Error downloading {url}: {e}")
    return None

def populate_gallery():
    print("Starting product gallery image population...")
    
    gallery_mapping = {
        "Aetherial Chronograph S1": [
            "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800",
            "https://images.unsplash.com/photo-1542496658-e33a6d0d50f6?w=800",
            "https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?w=800"
        ],

        "Aura Velvet Loafers": [
            "https://images.unsplash.com/photo-1535043934128-cf0b28d52f95?w=800",
            "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=800",
            "https://images.unsplash.com/photo-1549298916-b41d501d3772?w=800"
        ],
        "Vesper Leather Weekender": [
            "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=800",
            "https://images.unsplash.com/photo-1547949003-9792a18a2601?w=800",
            "https://images.unsplash.com/photo-1581605405669-fcdf81165afa?w=800"
        ],
        "Vortex Infinity 5G Phone": [
            "https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=800",
            "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=800",
            "https://images.unsplash.com/photo-1580910051074-3eb694886505?w=800"
        ],
        "Aura Sonic Noise-Canceling Buds": [
            "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800",
            "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=800",
            "https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800"
        ],
        "Urban Onyx Windbreaker": [
            "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=800",
            "https://images.unsplash.com/photo-1551488831-00ddcb6c6bd3?w=800",
            "https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=800"
        ]
    }
    
    oppo_images = [
        r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\903aa9b7-710f-4245-ab6b-73ce717fedf6\oppo_f21_pro_front_1778656697407.png",
        r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\903aa9b7-710f-4245-ab6b-73ce717fedf6\oppo_f21_pro_camera_1778656722786.png",
        r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\903aa9b7-710f-4245-ab6b-73ce717fedf6\oppo_f21_pro_angled_1778656741473.png"
    ]
    
    for product_name, urls in gallery_mapping.items():
        try:
            product = Product.objects.get(name=product_name)
            # Clean existing images to avoid duplicates
            ProductImage.objects.filter(product=product).delete()
            print(f"Populating images for {product.name}...")
            for idx, url in enumerate(urls):
                fp = download_image(url)
                if fp:
                    img_obj = ProductImage(product=product)
                    file_name = f"{product.slug}_gal_{idx}.jpg"
                    img_obj.image.save(file_name, File(fp), save=True)
                    print(f"  - Added gallery image {idx + 1}")
        except Product.DoesNotExist:
            print(f"Product not found: {product_name}")

    # Populate OPPO product
    try:
        oppo_product = Product.objects.get(name__icontains="OPPO F21 Pro")
        ProductImage.objects.filter(product=oppo_product).delete()
        print(f"Populating local generated images for {oppo_product.name}...")
        for idx, path in enumerate(oppo_images):
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    img_obj = ProductImage(product=oppo_product)
                    file_name = f"oppo_f21_pro_gal_{idx}.png"
                    img_obj.image.save(file_name, File(f), save=True)
                    print(f"  - Added local image {idx + 1} from path")
            else:
                print(f"  - Warning: Local image path does not exist: {path}")
    except Product.DoesNotExist:
        print("OPPO F21 Pro product not found in database.")

    print("Gallery population completed successfully!")

if __name__ == "__main__":
    populate_gallery()
