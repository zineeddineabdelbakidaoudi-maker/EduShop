"""Seed database — CLEAN DELIVERY VERSION.
Creates only the admin account. No demo products or sellers.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.base import engine, SessionLocal
from models.user import User, UserRole
import models  # ensure all models are registered
from db.base import Base
from passlib.context import CryptContext

Base.metadata.create_all(bind=engine)
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def seed():
    db = SessionLocal()
    try:
        # Create admin account only if it does not already exist
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
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seed error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
