import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./edushop.db")

# Render uses 'postgres://', SQLAlchemy 2.0+ requires 'postgresql://'
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

Base = declarative_base()

def init_engine():
    global DATABASE_URL
    if not DATABASE_URL.startswith("sqlite"):
        try:
            test_engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5}
            )
            # Test immediate connection
            with test_engine.connect():
                pass
            print(f"[OK] Connected successfully to PostgreSQL database!")
            return test_engine
        except Exception as e:
            print(f"[WARN] PostgreSQL connection failed ({e}). Falling back to SQLite local database.")
            DATABASE_URL = "sqlite:///./edushop.db"

    return create_engine("sqlite:///./edushop.db", connect_args={"check_same_thread": False})

engine = init_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
