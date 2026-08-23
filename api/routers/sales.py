from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from db.base import get_db
from models.sale import Sale, SaleItem, PaymentMethod
from models.product import Product
from models.stock import SellerStock
from models.user import User, UserRole
from api.deps import require_admin, require_seller, get_current_user
from api.websocket import manager

router = APIRouter(prefix="/api/sales", tags=["sales"])

class SaleItemCreate(BaseModel):
    product_id: int
    quantity: int

class SaleCreate(BaseModel):
    items: List[SaleItemCreate]
    payment_method: PaymentMethod = PaymentMethod.cash
    discount: float = 0.0
    notes: Optional[str] = None

def format_sale(sale: Sale, include_purchase_price: bool = False) -> dict:
    items = []
    for si in sale.items:
        item = {
            "product_id": si.product_id,
            "name_fr": si.product.name_fr if si.product else "",
            "quantity": si.quantity,
            "unit_price": si.unit_price,
            "total": si.quantity * si.unit_price,
        }
        if include_purchase_price:
            item["purchase_price"] = si.purchase_price
            item["profit"] = (si.unit_price - si.purchase_price) * si.quantity
        items.append(item)
    return {
        "id": sale.id, "seller_id": sale.seller_id,
        "seller_name": sale.seller.username if sale.seller else "",
        "total": sale.total, "discount": sale.discount,
        "payment_method": sale.payment_method, "is_return": sale.is_return,
        "notes": sale.notes, "created_at": sale.created_at, "items": items,
    }

@router.post("", status_code=201)
async def create_sale(data: SaleCreate, db: Session = Depends(get_db), seller: User = Depends(require_seller)):
    total = 0.0
    locked_stocks = []

    # Validate and lock all items first (prevents partial commits)
    for item in data.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(400, f"Produit ID {item.product_id} introuvable")

        ss = db.query(SellerStock).with_for_update().filter_by(
            seller_id=seller.id, product_id=item.product_id
        ).first()
        if not ss or ss.quantity < item.quantity:
            avail = ss.quantity if ss else 0
            raise HTTPException(400, f"Stock insuffisant pour '{product.name_fr}' (disponible: {avail})")

        total += item.quantity * product.sell_price
        locked_stocks.append((ss, product, item.quantity))

    total -= data.discount

    # Apply changes atomically
    sale = Sale(
        seller_id=seller.id, total=total, discount=data.discount,
        payment_method=data.payment_method, notes=data.notes, is_return=False
    )
    db.add(sale)
    db.flush()

    for ss, product, qty in locked_stocks:
        ss.quantity -= qty
        si = SaleItem(
            sale_id=sale.id, product_id=product.id, quantity=qty,
            unit_price=product.sell_price, purchase_price=product.purchase_price
        )
        db.add(si)

    db.commit()
    db.refresh(sale)

    await manager.broadcast_admin("sale.created", {
        "seller_name": seller.username,
        "total": total,
        "product_count": len(data.items),
        "sale_id": sale.id,
    })

    return format_sale(sale, include_purchase_price=False)

@router.post("/{sale_id}/return")
async def return_sale(sale_id: int, db: Session = Depends(get_db), seller: User = Depends(require_seller)):
    sale = db.query(Sale).filter(Sale.id == sale_id, Sale.seller_id == seller.id).first()
    if not sale:
        raise HTTPException(404, "Vente introuvable")
    if sale.is_return:
        raise HTTPException(400, "Cette vente est déjà un retour")

    for si in sale.items:
        ss = db.query(SellerStock).with_for_update().filter_by(
            seller_id=seller.id, product_id=si.product_id
        ).first()
        if ss:
            ss.quantity += si.quantity
        else:
            db.add(SellerStock(seller_id=seller.id, product_id=si.product_id, quantity=si.quantity))

    sale.is_return = True
    db.commit()

    await manager.broadcast_admin("sale.returned", {"sale_id": sale_id, "seller_name": seller.username})
    return format_sale(sale, include_purchase_price=False)

@router.get("/report")
def sales_report(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    q = db.query(Sale)
    if date_from:
        q = q.filter(Sale.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.filter(Sale.created_at <= datetime.fromisoformat(date_to))
    sales = q.all()

    total_revenue = sum(s.total for s in sales if not s.is_return)
    total_profit = sum(
        sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items)
        for s in sales if not s.is_return
    )
    total_returns = sum(1 for s in sales if s.is_return)
    total_transactions = sum(1 for s in sales if not s.is_return)

    per_seller = {}
    for s in sales:
        sid = s.seller_id
        if sid not in per_seller:
            per_seller[sid] = {"seller_id": sid, "name": s.seller.username if s.seller else "", "revenue": 0, "profit": 0, "count": 0, "returns": 0}
        if not s.is_return:
            per_seller[sid]["revenue"] += s.total
            per_seller[sid]["profit"] += sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items)
            per_seller[sid]["count"] += 1
        else:
            per_seller[sid]["returns"] += 1

    daily = {}
    for s in sales:
        if not s.is_return:
            d = s.created_at.date().isoformat()
            daily.setdefault(d, {"date": d, "revenue": 0, "profit": 0})
            daily[d]["revenue"] += s.total
            daily[d]["profit"] += sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items)

    return {
        "total_revenue": total_revenue, "total_profit": total_profit,
        "total_transactions": total_transactions, "total_returns": total_returns,
        "per_seller": list(per_seller.values()),
        "daily": sorted(daily.values(), key=lambda x: x["date"]),
    }

@router.get("/me")
def my_sales(
    skip: int = 0, limit: int = 50,
    db: Session = Depends(get_db), seller: User = Depends(require_seller)
):
    sales = db.query(Sale).filter(Sale.seller_id == seller.id).order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
    return [format_sale(s) for s in sales]

@router.get("")
def list_sales(
    seller_id: Optional[int] = None, date_from: Optional[str] = None,
    date_to: Optional[str] = None, is_return: Optional[bool] = None,
    skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    q = db.query(Sale)
    if seller_id:
        q = q.filter(Sale.seller_id == seller_id)
    if date_from:
        q = q.filter(Sale.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.filter(Sale.created_at <= datetime.fromisoformat(date_to))
    if is_return is not None:
        q = q.filter(Sale.is_return == is_return)
    sales = q.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
    return [format_sale(s, include_purchase_price=True) for s in sales]

@router.get("/{sale_id}")
def get_sale(sale_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(404, "Vente introuvable")
    if current_user.role == UserRole.seller and sale.seller_id != current_user.id:
        raise HTTPException(403, "Accès refusé")
    include_prices = current_user.role == UserRole.admin
    return format_sale(sale, include_purchase_price=include_prices)
