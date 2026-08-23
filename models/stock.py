import datetime
from sqlalchemy import Column, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from db.base import Base

class GlobalStock(Base):
    __tablename__ = "global_stock"
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    quantity = Column(Integer, default=0)
    product = relationship("Product", back_populates="global_stock")

class SellerStock(Base):
    __tablename__ = "seller_stock"
    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint("seller_id", "product_id"),)
    seller = relationship("User", back_populates="seller_stock")
    product = relationship("Product", back_populates="seller_stock")

class StockTransfer(Base):
    __tablename__ = "stock_transfers"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    transferred_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    product = relationship("Product", back_populates="transfers")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="transfers_received")
    transferred_by = relationship("User", foreign_keys=[transferred_by_id], back_populates="transfers_made")
