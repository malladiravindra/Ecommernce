import os
import django
from django.core.files import File

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecommernce.settings')
django.setup()

from shop.models import Category, Product, ProductImage

def seed_database():
    print("Beginning database seeding process...")

    products_data = [
        {
            "category_name": "Mobile products",
            "category_desc": "High performance smartphones and mobile accessories.",
            "name": "OPPO F21 Pro (Cosmic Black, 128 GB)",
            "slug": "oppo-f21-pro-cosmic-black-128-gb",
            "description": (
                "Experience next-level design and performance with the OPPO F21 Pro in Cosmic Black. "
                "Features a brilliant 6.43-inch 90Hz AMOLED display, powered by the Qualcomm Snapdragon 680 processor. "
                "Equipped with 8 GB of RAM and 128 GB of internal storage. Captures stunning photos with a 64 MP AI Triple Rear Camera "
                "featuring an industry-first Orbit Light ring around the microlens, and a 32 MP flagship front camera. "
                "Supported by a long-lasting 4500 mAh battery with 33W SUPERVOOC fast charging."
            ),
            "price": 27999.00,
            "discount_price": 17999.00,
            "stock": 50,
            "featured": True,
            "is_highlight": True,
            "image_path": r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\oppo_f21_pro_cosmic_black_1779172724335.png",
            "gallery_paths": [
                r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\oppo_f21_pro_front_1779172741897.png",
                r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\oppo_f21_pro_camera_1779172759750.png"
            ]
        },
        {
            "category_name": "Luxury Watchware",
            "category_desc": "Finest automatic luxury chronometers and watches.",
            "name": "Rolex Submariner Date (Stainless Steel)",
            "slug": "rolex-submariner-date-stainless-steel",
            "description": (
                "The Rolex Submariner Date is the benchmark for divers' watches. Crafted from Oystersteel, "
                "it features a unidirectional rotating black Cerachrom bezel, automatic mechanical movement, "
                "and an Oyster bracelet. Waterproof to 300 meters (1,000 feet)."
            ),
            "price": 850000.00,
            "discount_price": 799000.00,
            "stock": 5,
            "featured": True,
            "is_highlight": False,
            "image_path": r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\rolex_submariner_1779173020892.png",
            "gallery_paths": []
        },
        {
            "category_name": "Modern Footwear",
            "category_desc": "High performance athletic and designer sneakers.",
            "name": "Adidas Ultraboost Premium (Triple Black)",
            "slug": "adidas-ultraboost-premium-triple-black",
            "description": (
                "Experience infinite energy return with Adidas Ultraboost running shoes. Features a sleek "
                "Primeknit wrap upper for maximum breathability, responsive Boost midsole technology, and "
                "Continental rubber outsole for unbeatable grip."
            ),
            "price": 18999.00,
            "discount_price": 14999.00,
            "stock": 120,
            "featured": True,
            "is_highlight": False,
            "image_path": r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\adidas_ultraboost_1779173042240.png",
            "gallery_paths": []
        },
        {
            "category_name": "Premium Apparel",
            "category_desc": "Designer clothing and elite apparel collections.",
            "name": "Moncler Classic Puffer Jacket (Glossy Black)",
            "slug": "moncler-classic-puffer-jacket-glossy-black",
            "description": (
                "Crafted for extreme warmth and timeless street style, the Moncler puffer jacket features "
                "premium down fill insulation, a glossy weather-resistant nylon shell, detachable hood, "
                "and signature Moncler brand emblem on the sleeve."
            ),
            "price": 145000.00,
            "discount_price": 129000.00,
            "stock": 8,
            "featured": True,
            "is_highlight": False,
            "image_path": r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\moncler_jacket_1779173064168.png",
            "gallery_paths": []
        },
        {
            "category_name": "Watches",
            "category_desc": "Sleek smartwatches and tracking accessories.",
            "name": "Apple Watch Series 9 (GPS + Cellular, 45mm)",
            "slug": "apple-watch-series-9-cellular-45mm",
            "description": (
                "Smarter, brighter, and more powerful. Features the S9 SiP processor, a double-tap gesture, "
                "Always-On Retina display, advanced blood oxygen monitoring, ECG tracking, and crash detection. "
                "Fully integrated with Cellular connectivity."
            ),
            "price": 45999.00,
            "discount_price": 41999.00,
            "stock": 40,
            "featured": True,
            "is_highlight": False,
            "image_path": r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\apple_watch_1779173083002.png",
            "gallery_paths": []
        },
        {
            "category_name": "Earphones",
            "category_desc": "Premium wireless audio and noise cancelling earphones.",
            "name": "Sony WF-1000XM5 Noise Cancelling Earbuds",
            "slug": "sony-wf-1000xm5-noise-cancelling-earbuds",
            "description": (
                "The best noise-cancelling earbuds on the market. Sony WF-1000XM5 features custom Dynamic Driver X "
                "for rich vocals, HD Noise Cancelling Processor QN2e, multi-point connection, and crystal-clear call quality."
            ),
            "price": 24999.00,
            "discount_price": 19999.00,
            "stock": 85,
            "featured": True,
            "is_highlight": False,
            "image_path": r"C:\Users\Malladi Ravidra\.gemini\antigravity\brain\e76ea96e-7d9c-4961-8530-38c36c00d4ef\sony_earbuds_1779173101953.png",
            "gallery_paths": []
        }
    ]

    for data in products_data:
        # Get or create Category
        category, cat_created = Category.objects.get_or_create(
            name=data["category_name"],
            defaults={"description": data["category_desc"]}
        )
        if cat_created:
            print(f"Created Category '{category.name}'")
        else:
            print(f"Found Category '{category.name}'")

        # Get or create Product
        product, prod_created = Product.objects.update_or_create(
            slug=data["slug"],
            defaults={
                "category": category,
                "name": data["name"],
                "description": data["description"],
                "price": data["price"],
                "discount_price": data["discount_price"],
                "stock": data["stock"],
                "featured": data["featured"],
                "is_highlight": data["is_highlight"],
                "is_active": True
            }
        )

        # Save main product image
        if os.path.exists(data["image_path"]):
            with open(data["image_path"], 'rb') as f:
                product.image.save(os.path.basename(data["image_path"]), File(f), save=True)
            print(f"Main image saved successfully for {product.name}!")
        else:
            print(f"Warning: Image file not found at {data['image_path']}")

        # Save gallery images
        if data["gallery_paths"]:
            ProductImage.objects.filter(product=product).delete()
            for idx, path in enumerate(data["gallery_paths"]):
                if os.path.exists(path):
                    with open(path, 'rb') as f:
                        img_obj = ProductImage(product=product)
                        img_obj.image.save(f"gal_{idx}_{os.path.basename(path)}", File(f), save=True)
                    print(f"Gallery image {idx+1} saved successfully for {product.name}!")
                else:
                    print(f"Warning: Gallery image file not found at {path}")

        if prod_created:
            print(f"Product '{product.name}' successfully created!")
        else:
            print(f"Product '{product.name}' successfully updated!")

if __name__ == "__main__":
    seed_database()
