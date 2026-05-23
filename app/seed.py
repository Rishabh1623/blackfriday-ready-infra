"""
Seed script — creates tables and populates test data.
Run once after terraform apply:
  export $(cat .env | xargs)
  python3 seed.py
"""

import os
import random
import uuid
from datetime import datetime, timedelta

import psycopg2

DB_HOST = os.environ.get("RDS_PROXY_ENDPOINT", os.environ.get("DB_HOST", "localhost"))
DB_NAME = os.environ.get("DB_NAME", "blackfriday")
DB_USER = os.environ.get("DB_USER", "blackfridayadmin")
DB_PASSWORD = os.environ["DB_PASSWORD"]

PRODUCTS = [
    ("4K Smart TV 55\"", 699.99, "Electronics"),
    ("4K Smart TV 65\"", 999.99, "Electronics"),
    ("Wireless Noise-Cancelling Headphones", 249.99, "Electronics"),
    ("Bluetooth Speaker Portable", 79.99, "Electronics"),
    ("Laptop 15\" Core i7", 1199.99, "Computers"),
    ("Gaming Laptop RTX 4060", 1499.99, "Computers"),
    ("Mechanical Keyboard RGB", 129.99, "Computers"),
    ("Gaming Mouse 25K DPI", 69.99, "Computers"),
    ("27\" 144Hz Monitor", 329.99, "Computers"),
    ("USB-C Hub 10-in-1", 49.99, "Computers"),
    ("Smartwatch Series 9", 399.99, "Wearables"),
    ("Fitness Tracker Band", 59.99, "Wearables"),
    ("Wireless Earbuds Pro", 179.99, "Electronics"),
    ("Action Camera 4K", 299.99, "Electronics"),
    ("Instant Pot 8Qt", 89.99, "Kitchen"),
    ("Air Fryer XL 5.8Qt", 119.99, "Kitchen"),
    ("Coffee Maker 12-Cup", 79.99, "Kitchen"),
    ("Stand Mixer 5Qt", 349.99, "Kitchen"),
    ("Blender High-Speed", 129.99, "Kitchen"),
    ("Toaster Oven Convection", 89.99, "Kitchen"),
    ("Robot Vacuum Wi-Fi", 299.99, "Home"),
    ("Smart Thermostat", 149.99, "Home"),
    ("Security Camera 4K", 99.99, "Home"),
    ("Smart Doorbell Video", 179.99, "Home"),
    ("LED Strip Lights 32ft", 29.99, "Home"),
    ("Massage Chair Recliner", 799.99, "Furniture"),
    ("Standing Desk Electric", 499.99, "Furniture"),
    ("Gaming Chair Ergonomic", 299.99, "Furniture"),
    ("Monitor Arm Dual", 89.99, "Furniture"),
    ("Bookshelf 5-Tier", 149.99, "Furniture"),
    ("Running Shoes Men's", 119.99, "Sports"),
    ("Running Shoes Women's", 109.99, "Sports"),
    ("Yoga Mat Non-Slip", 39.99, "Sports"),
    ("Resistance Bands Set", 24.99, "Sports"),
    ("Dumbbells Adjustable 50lb", 249.99, "Sports"),
    ("Pull-Up Bar Doorway", 34.99, "Sports"),
    ("Jump Rope Speed", 19.99, "Sports"),
    ("Foam Roller Trigger", 29.99, "Sports"),
    ("Backpack Travel 40L", 89.99, "Bags"),
    ("Laptop Bag Slim 15\"", 49.99, "Bags"),
    ("Hardside Luggage 28\"", 199.99, "Travel"),
    ("Packing Cubes Set 6", 29.99, "Travel"),
    ("Travel Pillow Memory Foam", 39.99, "Travel"),
    ("Passport Holder RFID", 19.99, "Travel"),
    ("Power Bank 26800mAh", 59.99, "Electronics"),
    ("Fast Charger 65W GaN", 44.99, "Electronics"),
    ("MagSafe Wallet Card", 34.99, "Accessories"),
    ("Phone Case Clear MagSafe", 24.99, "Accessories"),
    ("Screen Protector 3-Pack", 14.99, "Accessories"),
    ("Cable Management Kit", 19.99, "Accessories"),
    ("Webcam 4K 60fps", 149.99, "Computers"),
    ("Ring Light 18\"", 79.99, "Photography"),
    ("Tripod Carbon Fiber", 129.99, "Photography"),
    ("Microphone USB Condenser", 99.99, "Audio"),
    ("HDMI Cable 4K 6ft", 12.99, "Cables"),
    ("Ethernet Cable Cat8 25ft", 18.99, "Cables"),
    ("Wall Mount TV 55-85\"", 49.99, "Home"),
    ("Smart Plug Wi-Fi 4-Pack", 29.99, "Home"),
    ("Extension Cord Surge 6-Outlet", 24.99, "Home"),
    ("Humidifier Cool Mist", 44.99, "Home"),
    ("Air Purifier HEPA", 149.99, "Home"),
    ("Dehumidifier 35 Pint", 179.99, "Home"),
    ("Tower Fan 36\"", 89.99, "Home"),
    ("Space Heater Ceramic", 49.99, "Home"),
    ("Electric Blanket Heated", 59.99, "Bedding"),
    ("Mattress Topper Memory Foam", 149.99, "Bedding"),
    ("Pillow Set King 2-Pack", 49.99, "Bedding"),
    ("Duvet Insert All-Season", 79.99, "Bedding"),
    ("Blackout Curtains 84\"", 39.99, "Bedding"),
    ("Baby Monitor 1080p", 149.99, "Baby"),
    ("Baby Gate Extra Wide", 69.99, "Baby"),
    ("Car Seat Convertible", 299.99, "Baby"),
    ("Stroller Lightweight", 199.99, "Baby"),
    ("Baby Bouncer Swing", 149.99, "Baby"),
    ("Dog Bed Orthopedic L", 89.99, "Pets"),
    ("Cat Tree Tower 72\"", 119.99, "Pets"),
    ("Dog Leash Retractable", 24.99, "Pets"),
    ("Pet Carrier Airline", 59.99, "Pets"),
    ("Automatic Pet Feeder", 79.99, "Pets"),
    ("Board Game Catan", 44.99, "Toys"),
    ("LEGO Technic Set", 129.99, "Toys"),
    ("RC Car Off-Road", 89.99, "Toys"),
    ("Drone with Camera", 249.99, "Toys"),
    ("Puzzle 1000 Piece", 19.99, "Toys"),
    ("Guitar Acoustic Beginner", 199.99, "Music"),
    ("Keyboard Piano 88-Key", 449.99, "Music"),
    ("Drawing Tablet Digital", 179.99, "Art"),
    ("Paint Set Acrylic 60", 39.99, "Art"),
    ("Sketch Pad A4 100-Sheet", 14.99, "Art"),
    ("Book Kindle Paperwhite", 139.99, "Electronics"),
    ("Sunglasses Polarized", 49.99, "Fashion"),
    ("Watch Analog Minimalist", 129.99, "Fashion"),
    ("Wallet Slim RFID", 39.99, "Fashion"),
    ("Belt Leather Reversible", 34.99, "Fashion"),
    ("Perfume Eau de Toilette", 79.99, "Beauty"),
    ("Skincare Set 5-Piece", 89.99, "Beauty"),
    ("Electric Toothbrush", 69.99, "Health"),
    ("Blood Pressure Monitor", 59.99, "Health"),
    ("Thermometer Digital", 29.99, "Health"),
]


def create_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id         SERIAL PRIMARY KEY,
            name       TEXT        NOT NULL,
            price      NUMERIC(10,2) NOT NULL,
            category   TEXT        NOT NULL,
            created_at TIMESTAMP   DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            product_id  INT REFERENCES products(id) PRIMARY KEY,
            quantity    INT         NOT NULL DEFAULT 0,
            updated_at  TIMESTAMP   DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id            SERIAL PRIMARY KEY,
            session_token TEXT        NOT NULL,
            user_id       TEXT        NOT NULL,
            product_id    INT         NOT NULL,
            quantity      INT         NOT NULL,
            created_at    TIMESTAMP   DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    TEXT        NOT NULL,
            expires_at TIMESTAMP   NOT NULL
        )
    """)


def seed_products(cur) -> list[int]:
    for name, price, category in PRODUCTS:
        cur.execute(
            "INSERT INTO products (name, price, category) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (name, price, category),
        )
    # Fetch all IDs including pre-existing rows that ON CONFLICT skipped
    cur.execute("SELECT id FROM products ORDER BY id")
    return [row[0] for row in cur.fetchall()]


def seed_inventory(cur, product_ids: list[int]):
    for pid in product_ids:
        qty = random.randint(50, 500)
        cur.execute(
            "INSERT INTO inventory (product_id, quantity) VALUES (%s, %s) "
            "ON CONFLICT (product_id) DO UPDATE SET quantity = EXCLUDED.quantity",
            (pid, qty),
        )


def seed_sessions(cur):
    cur.execute("DELETE FROM sessions WHERE expires_at < NOW()")
    expires_at = datetime.utcnow() + timedelta(hours=24)
    for i in range(1000):
        user_id = f"user_{i + 1:04d}"
        token = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (token) DO NOTHING",
            (token, user_id, expires_at),
        )


def main():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=5432,
        connect_timeout=10,
    )
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            print("Creating tables...")
            create_tables(cur)

            print("Seeding 100 products...")
            product_ids = seed_products(cur)

            print(f"Seeding inventory for {len(product_ids)} products...")
            seed_inventory(cur, product_ids)

            print("Seeding 1000 session tokens...")
            seed_sessions(cur)

        conn.commit()
        print("Seed completed successfully.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
