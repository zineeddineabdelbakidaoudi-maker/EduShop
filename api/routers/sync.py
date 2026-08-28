from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.base import get_db
from models.product import Product
from models.stock import SellerStock
from models.sale import Sale, SaleItem, PaymentMethod
from models.user import User, UserRole
from api.deps import require_seller, get_current_user
from api.websocket import manager

router = APIRouter(prefix="/api/sync", tags=["sync"])

class OfflineSaleItem(BaseModel):
    product_id: int
    quantity: int
    unit_price: float

class OfflineSale(BaseModel):
    local_id: int
    created_at: str
    payment_method: str = "cash"
    discount: float = 0.0
    notes: Optional[str] = None
    is_return: bool = False
    items: List[OfflineSaleItem]

class PushRequest(BaseModel):
    sales: List[OfflineSale]

@router.get("/pull")
def sync_pull(db: Session = Depends(get_db), seller: User = Depends(require_seller)):
    """Seller pulls latest assigned products & stock quantities from server."""
    stocks = db.query(SellerStock).filter_by(seller_id=seller.id).all()
    products_data = []
    for ss in stocks:
        p = ss.product
        if p:
            products_data.append({
                "id": p.id,
                "code_article": p.code_article,
                "barcode": p.barcode,
                "name_fr": p.name_fr,
                "name_ar": p.name_ar,
                "category": p.category,
                "sell_price": p.sell_price,
                "min_quantity": p.min_quantity,
                "fast_panel": bool(p.fast_panel),
                "quantity": ss.quantity
            })
    return {
        "server_time": datetime.utcnow().isoformat(),
        "products": products_data
    }

@router.post("/push")
async def sync_push(data: PushRequest, db: Session = Depends(get_db), seller: User = Depends(require_seller)):
    """Seller uploads offline sales to server. Server processes them atomically."""
    synced_local_ids = []

    for osale in data.sales:
        try:
            # Parse created_at
            try:
                sale_time = datetime.fromisoformat(osale.created_at)
            except Exception:
                sale_time = datetime.utcnow()

            # Calculate total
            total = sum(item.quantity * item.unit_price for item in osale.items) - osale.discount

            # Map payment method
            pm = PaymentMethod.cash
            if osale.payment_method.lower() == "card":
                pm = PaymentMethod.card
            elif osale.payment_method.lower() == "mixed":
                pm = PaymentMethod.mixed

            # Create sale
            sale = Sale(
                seller_id=seller.id,
                total=max(0.0, total),
                discount=osale.discount,
                payment_method=pm,
                is_return=osale.is_return,
                notes=osale.notes,
                created_at=sale_time
            )
            db.add(sale)
            db.flush()

            # Process items
            for item in osale.items:
                product = db.query(Product).filter_by(id=item.product_id).first()
                purchase_p = product.purchase_price if product else 0.0

                si = SaleItem(
                    sale_id=sale.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    purchase_price=purchase_p
                )
                db.add(si)

                # Update server seller stock
                ss = db.query(SellerStock).filter_by(seller_id=seller.id, product_id=item.product_id).first()
                if ss:
                    if osale.is_return:
                        ss.quantity += item.quantity
                    else:
                        ss.quantity = max(0, ss.quantity - item.quantity)

            db.commit()
            synced_local_ids.append(osale.local_id)

            # Notify Admin live dashboard via WebSocket
            await manager.broadcast_admin("sale.created", {
                "seller_name": seller.username,
                "total": total,
                "product_count": len(osale.items),
                "sale_id": sale.id,
                "is_offline_sync": True
            })

        except Exception as e:
            db.rollback()
            print(f"[SYNC ERROR] Sale {osale.local_id}: {e}")

    return {
        "status": "success",
        "synced_ids": synced_local_ids
    }
