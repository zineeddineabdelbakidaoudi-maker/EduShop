from typing import List, Optional
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.base import get_db
from models.product import Product
from models.stock import GlobalStock, SellerStock
from models.user import User
from api.deps import require_admin
from api.websocket import manager

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

class InventoryAdjustmentItem(BaseModel):
    product_id: int
    counted_quantity: int
    reason: Optional[str] = "Ajustement Inventaire"

class InventoryAdjustmentRequest(BaseModel):
    items: List[InventoryAdjustmentItem]
    notes: Optional[str] = None

@router.get("/sheet")
def get_inventory_sheet(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    products = db.query(Product).order_by(Product.name_fr).all()
    result = []
    total_val_purchase = 0.0
    total_val_sell = 0.0
    total_units = 0

    for p in products:
        qty = (p.global_stock.quantity if p.global_stock else 0)
        if hasattr(p, 'seller_stock') and p.seller_stock:
            qty += sum(ss.quantity for ss in p.seller_stock if ss.quantity > 0)
        val_p = qty * (p.purchase_price or 0.0)
        val_s = qty * (p.sell_price or 0.0)
        total_val_purchase += val_p
        total_val_sell += val_s
        total_units += qty

        result.append({
            "id": p.id,
            "code_article": p.code_article,
            "barcode": p.barcode or "",
            "name_fr": p.name_fr,
            "name_ar": p.name_ar or "",
            "category": p.category or "Général",
            "purchase_price": p.purchase_price or 0.0,
            "sell_price": p.sell_price or 0.0,
            "theoretical_stock": qty,
            "value_purchase": round(val_p, 2),
            "value_sell": round(val_s, 2),
        })

    return {
        "products": result,
        "summary": {
            "total_products": len(products),
            "total_units": total_units,
            "total_value_purchase": round(total_val_purchase, 2),
            "total_value_sell": round(total_val_sell, 2)
        }
    }

@router.post("/adjust")
async def adjust_inventory(req: InventoryAdjustmentRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    adjusted_count = 0
    total_diff_units = 0
    total_diff_value = 0.0

    for it in req.items:
        p = db.query(Product).options(joinedload(Product.global_stock)).filter(Product.id == it.product_id).first()
        if not p:
            continue
        
        gs = p.global_stock
        if not gs:
            gs = GlobalStock(product_id=p.id, quantity=0)
            db.add(gs)
            db.flush()

        old_qty = gs.quantity
        new_qty = max(0, it.counted_quantity)
        diff = new_qty - old_qty
        
        gs.quantity = new_qty
        adjusted_count += 1
        total_diff_units += diff
        total_diff_value += diff * (p.purchase_price or 0.0)

    db.commit()
    try:
        await manager.broadcast_all("stock.updated_all", {})
    except Exception:
        pass
    return {
        "status": "success",
        "adjusted_products": adjusted_count,
        "total_diff_units": total_diff_units,
        "total_diff_value": round(total_diff_value, 2),
        "applied_at": datetime.datetime.utcnow().isoformat()
    }
