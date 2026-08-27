import datetime
import re
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import relationship
from db.base import Base

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    code_article = Column(String, unique=True, index=True, nullable=False)
    barcode = Column(String, nullable=True, index=True)  # Supports up to 5 comma-separated barcodes
    name_fr = Column(String, nullable=False)
    name_ar = Column(String, nullable=True)
    category = Column(String, nullable=True)
    purchase_price = Column(Float, default=0.0)
    sell_price = Column(Float, default=0.0)
    min_quantity = Column(Integer, default=5)
    description = Column(String, nullable=True)
    buyer = Column(String, default="Bilal", nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    @property
    def barcode_list(self) -> list:
        if not self.barcode:
            return []
        return [b.strip() for b in re.split(r'[,;|\s]+', self.barcode) if b.strip()][:5]

    global_stock = relationship("GlobalStock", back_populates="product", uselist=False, cascade="all, delete-orphan")
    seller_stock = relationship("SellerStock", back_populates="product", cascade="all, delete-orphan")
    sale_items = relationship("SaleItem", back_populates="product")
    transfers = relationship("StockTransfer", back_populates="product")
