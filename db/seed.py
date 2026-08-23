"""Seed database with demo data. Safe to run multiple times (idempotent)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.base import engine, SessionLocal
from models.user import User, UserRole
from models.product import Product
from models.stock import GlobalStock, SellerStock
from models.sale import Sale, SaleItem
from models.supplier import Supplier, PurchaseInvoice
import models  # ensure all models are registered
from passlib.context import CryptContext
import datetime

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Import Base after all models are loaded
from db.base import Base
Base.metadata.create_all(bind=engine)

PRODUCTS_DATA = [
    {"code_article": "ART-001", "barcode": "3000000000001", "name_fr": "Stylo Bic Cristal", "name_ar": "قلم بيك", "category": "Papeterie", "purchase_price": 5.0, "sell_price": 10.0, "min_quantity": 10, "stock": 100},
    {"code_article": "ART-002", "barcode": "3000000000002", "name_fr": "Cahier 200 Pages", "name_ar": "دفتر 200 صفحة", "category": "Cahiers", "purchase_price": 40.0, "sell_price": 70.0, "min_quantity": 5, "stock": 60},
    {"code_article": "ART-003", "barcode": "3000000000003", "name_fr": "Règle 30cm Plastique", "name_ar": "مسطرة 30 سم", "category": "Accessoires", "purchase_price": 8.0, "sell_price": 15.0, "min_quantity": 10, "stock": 80},
    {"code_article": "ART-004", "barcode": "3000000000004", "name_fr": "Colle UHU Stick", "name_ar": "غراء UHU", "category": "Accessoires", "purchase_price": 20.0, "sell_price": 35.0, "min_quantity": 5, "stock": 50},
    {"code_article": "ART-005", "barcode": "3000000000005", "name_fr": "Gomme Factis", "name_ar": "ممحاة فاكتيس", "category": "Papeterie", "purchase_price": 5.0, "sell_price": 12.0, "min_quantity": 15, "stock": 120},
]

USERS_DATA = [
    {"username": "admin", "pin": "1234", "role": UserRole.admin},
    {"username": "thel", "pin": "0000", "role": UserRole.seller},
    {"username": "seller2", "pin": "0000", "role": UserRole.seller},
    {"username": "seller3", "pin": "0000", "role": UserRole.seller},
    {"username": "seller4", "pin": "0000", "role": UserRole.seller},
]

def seed():
    db = SessionLocal()
    try:
        # Users
        created_users = {}
        for ud in USERS_DATA:
            u = db.query(User).filter_by(username=ud["username"]).first()
            if not u:
                u = User(username=ud["username"], pin_hash=pwd_ctx.hash(ud["pin"]), role=ud["role"])
                db.add(u)
                db.flush()
            created_users[ud["username"]] = u.id

        db.commit()

        # Re-query to get real IDs
        for ud in USERS_DATA:
            u = db.query(User).filter_by(username=ud["username"]).first()
            created_users[ud["username"]] = u.id

        # Products + GlobalStock
        created_products = {}
        for pd in PRODUCTS_DATA:
            p = db.query(Product).filter_by(code_article=pd["code_article"]).first()
            if not p:
                p = Product(
                    code_article=pd["code_article"],
                    barcode=pd["barcode"],
                    name_fr=pd["name_fr"],
                    name_ar=pd["name_ar"],
                    category=pd["category"],
                    purchase_price=pd["purchase_price"],
                    sell_price=pd["sell_price"],
                    min_quantity=pd["min_quantity"],
                )
                db.add(p)
                db.flush()

                gs = GlobalStock(product_id=p.id, quantity=pd["stock"])
                db.add(gs)
            created_products[pd["code_article"]] = p.id

        db.commit()

        # Seller stock for "thel" — 20 units of each product
        thel_id = created_users["thel"]
        for code, pid in created_products.items():
            ss = db.query(SellerStock).filter_by(seller_id=thel_id, product_id=pid).first()
            if not ss:
                ss = SellerStock(seller_id=thel_id, product_id=pid, quantity=20)
                db.add(ss)
                # Decrement global stock accordingly
                gs = db.query(GlobalStock).filter_by(product_id=pid).first()
                if gs and gs.quantity >= 20:
                    gs.quantity -= 20

        db.commit()
        print("[OK] Seed complete!")
        print("   Admin: admin / PIN 1234")
        print("   Sellers: thel, seller2, seller3, seller4 / PIN 0000")
        print("   Products: 5 products seeded, 20 units each allocated to thel")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seed error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
