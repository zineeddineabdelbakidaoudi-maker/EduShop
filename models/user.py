import datetime, enum
from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.orm import relationship
from db.base import Base

class UserRole(str, enum.Enum):
    admin = "admin"
    seller = "seller"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    pin_hash = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.seller)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    sales = relationship("Sale", back_populates="seller")
    seller_stock = relationship("SellerStock", back_populates="seller", cascade="all, delete-orphan")
    transfers_received = relationship("StockTransfer", foreign_keys="StockTransfer.seller_id", back_populates="seller")
    transfers_made = relationship("StockTransfer", foreign_keys="StockTransfer.transferred_by_id", back_populates="transferred_by")
