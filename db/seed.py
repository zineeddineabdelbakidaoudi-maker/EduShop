"""Seed database — PostgreSQL / SQLite Universal Seed.
Creates admin account and initializes products if table is empty.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.base import engine, SessionLocal, Base
from models.user import User, UserRole
from models.product import Product
from models.stock import GlobalStock
import models  # ensure all models are registered
from passlib.context import CryptContext

Base.metadata.create_all(bind=engine)
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def seed():
    db = SessionLocal()
    try:
        # 1. Create admin account only if it does not already exist
        admin = db.query(User).filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                pin_hash=pwd_ctx.hash("1234"),
                role=UserRole.admin
            )
            db.add(admin)
            db.commit()
            print("[OK] Admin account created: admin / PIN 1234")
        else:
            print("[OK] Admin account already exists.")

        # 2. Seed initial 80 products if products table is empty
        prod_count = db.query(Product).count()
        if prod_count == 0:
            json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "products_extracted.json")
            if not os.path.exists(json_path):
                json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extracted_products.json")
            
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    prods = json.load(f)
                
                count = 0
                for it in prods:
                    name_fr = it.get("name_fr", "").strip()
                    if not name_fr:
                        continue
                    pa = float(it.get("purchase_price", 0.0))
                    pv = round(pa * 1.25, 2) if pa > 0 else 0.0
                    qty = int(it.get("initial_quantity", it.get("quantity", 0)))
                    code = it.get("code_article") or f"ART-{count+1000:04d}"
                    buyer = it.get("buyer") or "Houari"

                    p = Product(
                        code_article=code,
                        barcode=it.get("barcode") or None,
                        name_fr=name_fr,
                        category="Fournitures",
                        purchase_price=pa,
                        sell_price=pv,
                        min_quantity=5,
                        buyer=buyer
                    )
                    db.add(p)
                    db.flush()
                    gs = GlobalStock(product_id=p.id, quantity=qty)
                    db.add(gs)
                    count += 1
                
                db.commit()
                print(f"[OK] Seeded {count} initial products into database!")
            else:
                print("[INFO] No initial products json file found to seed.")
        else:
            print(f"[OK] Database already contains {prod_count} products.")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seed error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
