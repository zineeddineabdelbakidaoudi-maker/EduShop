from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from db.base import get_db
from models.sale import Sale, SaleItem, PaymentMethod
from models.product import Product
from models.stock import SellerStock, GlobalStock
from models.user import User, UserRole
from api.deps import require_admin, require_seller, get_current_user, get_current_user_any
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
    for si in (sale.items or []):
        p = si.product
        item = {
            "product_id": si.product_id,
            "name_fr": p.name_fr if p else "Article",
            "code_article": p.code_article if p else "",
            "quantity": si.quantity,
            "unit_price": float(si.unit_price or 0.0),
            "total": float((si.quantity or 0) * (si.unit_price or 0.0)),
        }
        if include_purchase_price:
            pa = float(si.purchase_price or 0.0)
            item["purchase_price"] = pa
            item["profit"] = float((item["unit_price"] - pa) * item["quantity"])
        items.append(item)

    dt_str = ""
    if sale.created_at:
        dt_str = sale.created_at.isoformat() if hasattr(sale.created_at, "isoformat") else str(sale.created_at)

    pm = sale.payment_method
    if hasattr(pm, "value"):
        pm = pm.value

    return {
        "id": sale.id,
        "seller_id": sale.seller_id,
        "seller_name": sale.seller.username if sale.seller else "",
        "total": float(sale.total or 0.0),
        "discount": float(sale.discount or 0.0),
        "payment_method": str(pm or "cash"),
        "is_return": bool(sale.is_return),
        "is_archived": bool(getattr(sale, "is_archived", False)),
        "notes": sale.notes or "",
        "created_at": dt_str,
        "items": items,
    }

@router.post("", status_code=201)
async def create_sale(data: SaleCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        total = 0.0
        locked_stocks = []

        # Validate and prepare stock adjustments
        for item in data.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                raise HTTPException(400, f"Produit ID {item.product_id} introuvable")

            stock_target = None
            stock_type = None

            # 1. Try seller stock first
            ss = db.query(SellerStock).with_for_update().filter_by(
                seller_id=current_user.id, product_id=item.product_id
            ).first()
            if ss and ss.quantity >= item.quantity:
                stock_target = ss
                stock_type = 'seller'
            else:
                # 2. Fallback to GlobalStock so sale at cash register never blocks
                gs = db.query(GlobalStock).with_for_update().filter_by(product_id=item.product_id).first()
                if not gs:
                    gs = GlobalStock(product_id=item.product_id, quantity=0)
                    db.add(gs)
                    db.flush()
                stock_target = gs
                stock_type = 'global'

            total += item.quantity * product.sell_price
            locked_stocks.append((stock_type, stock_target, product, item.quantity))

        total = max(0.0, total - (data.discount or 0.0))

        # Record Sale
        pm_val = data.payment_method
        if hasattr(pm_val, "value"):
            pm_val = pm_val.value

        sale = Sale(
            seller_id=current_user.id, total=total, discount=data.discount or 0.0,
            payment_method=str(pm_val or "cash"), notes=data.notes, is_return=False,
            is_archived=False
        )
        db.add(sale)
        db.flush()

        for stock_type, stock_target, product, qty in locked_stocks:
            stock_target.quantity -= qty
            si = SaleItem(
                sale_id=sale.id, product_id=product.id, quantity=qty,
                unit_price=product.sell_price, purchase_price=product.purchase_price
            )
            db.add(si)

        db.commit()
        db.refresh(sale)

        try:
            await manager.broadcast_admin("sale.created", {
                "seller_name": current_user.username,
                "total": total,
                "product_count": len(data.items),
                "sale_id": sale.id,
            })
        except Exception:
            pass

        return format_sale(sale, include_purchase_price=False)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Erreur enregistrement vente: {str(e)}")

@router.post("/{sale_id}/return")
async def return_sale(sale_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    is_admin = getattr(current_user.role, "value", str(current_user.role)).lower() == "admin"
    if is_admin:
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
    else:
        sale = db.query(Sale).filter(Sale.id == sale_id, Sale.seller_id == current_user.id).first()
        
    if not sale:
        raise HTTPException(404, "Vente introuvable")
    if sale.is_return:
        raise HTTPException(400, "Cette vente est déjà un retour")

    target_seller_id = sale.seller_id or current_user.id
    for si in sale.items:
        ss = db.query(SellerStock).with_for_update().filter_by(
            seller_id=target_seller_id, product_id=si.product_id
        ).first()
        if ss:
            ss.quantity += si.quantity
        else:
            db.add(SellerStock(seller_id=target_seller_id, product_id=si.product_id, quantity=si.quantity))

    sale.is_return = True
    db.commit()

    await manager.broadcast_admin("sale.returned", {"sale_id": sale_id, "seller_name": current_user.username})
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
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    try:
        role_str = getattr(current_user.role, "value", str(current_user.role)).lower()
        if role_str == "admin":
            sales = db.query(Sale).order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
        else:
            sales = db.query(Sale).filter(Sale.seller_id == current_user.id).order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
        return [format_sale(s) for s in sales]
    except Exception as e:
        print(f"[ERROR my_sales] {e}")
        return []

@router.get("")
def list_sales(
    seller_id: Optional[int] = None, date_from: Optional[str] = None,
    date_to: Optional[str] = None, is_return: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    try:
        q = db.query(Sale)
        if seller_id:
            q = q.filter(Sale.seller_id == seller_id)
        if date_from:
            q = q.filter(Sale.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            q = q.filter(Sale.created_at <= datetime.fromisoformat(date_to))
        if is_return is not None:
            q = q.filter(Sale.is_return == is_return)
        if is_archived is not None:
            try:
                q = q.filter(Sale.is_archived == is_archived)
            except Exception:
                pass
        sales = q.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
        return [format_sale(s, include_purchase_price=True) for s in sales]
    except Exception as e:
        print(f"[ERROR list_sales] {e}")
        return []

@router.get("/{sale_id}")
def get_sale(sale_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(404, "Vente introuvable")
    if current_user.role == UserRole.seller and sale.seller_id != current_user.id:
        raise HTTPException(403, "Accès refusé")
    include_prices = current_user.role == UserRole.admin
    return format_sale(sale, include_purchase_price=include_prices)

@router.post("/{sale_id}/toggle-archive")
def toggle_archive_sale(sale_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(404, "Vente introuvable")
    sale.is_archived = not bool(getattr(sale, "is_archived", False))
    db.commit()
    return {"id": sale.id, "is_archived": sale.is_archived}
