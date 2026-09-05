from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel
from passlib.context import CryptContext
from db.base import get_db
from models.user import User, UserRole
from models.sale import Sale, SaleItem
from models.stock import SellerStock, StockTransfer
from models.product import Product
from api.deps import require_admin

router = APIRouter(prefix="/api/sellers", tags=["sellers"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

class SellerCreate(BaseModel):
    username: str
    pin: str
    role: UserRole = UserRole.seller

class SellerUpdate(BaseModel):
    username: Optional[str] = None
    pin: Optional[str] = None
    role: Optional[UserRole] = None

class SellerMergeRequest(BaseModel):
    source_seller_id: int
    target_seller_id: int

def seller_stats(user: User, db: Session) -> dict:
    try:
        sales = db.query(Sale).filter(Sale.seller_id == user.id, Sale.is_return == False).all()
        returns = db.query(Sale).filter(Sale.seller_id == user.id, Sale.is_return == True).count()
        revenue = sum(s.total for s in sales)
        profit = sum(
            sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items)
            for s in sales
        )
    except Exception:
        sales, returns, revenue, profit = [], 0, 0.0, 0.0

    return {
        "id": user.id, "username": user.username, "role": user.role,
        "created_at": user.created_at,
        "total_sales": len(sales), "total_revenue": revenue,
        "total_profit": profit, "total_returns": returns,
    }

@router.get("")
def list_sellers(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sellers = db.query(User).filter(User.username != "admin").order_by(User.id.asc()).all()
    return [seller_stats(s, db) for s in sellers]

@router.get("/progress")
def get_sellers_progress(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Comprehensive progress tracking: Capital sent, Revenue, Profit, Remaining Stock per seller."""
    users = db.query(User).filter(User.username != "admin").order_by(User.id.asc()).all()
    
    sellers_progress = []
    
    grand_capital_sent = 0.0
    grand_revenue = 0.0
    grand_profit = 0.0
    grand_capital_remaining = 0.0
    grand_sell_value_remaining = 0.0
    grand_units_sent = 0
    grand_units_sold = 0
    grand_units_remaining = 0

    for u in users:
        seller_stocks = db.query(SellerStock).options(joinedload(SellerStock.product)).filter(SellerStock.seller_id == u.id).all()
        transfers = db.query(StockTransfer).options(joinedload(StockTransfer.product)).filter(StockTransfer.seller_id == u.id).all()
        sales = db.query(Sale).options(joinedload(Sale.items).joinedload(SaleItem.product)).filter(Sale.seller_id == u.id, Sale.is_return == False).all()
        
        prod_map = {}

        # Aggregate transfers
        for t in transfers:
            if not t.product:
                continue
            pid = t.product_id
            if pid not in prod_map:
                prod_map[pid] = {
                    "product_id": pid,
                    "name_fr": t.product.name_fr,
                    "code_article": t.product.code_article or "",
                    "barcode": t.product.barcode or "",
                    "buyer": t.product.buyer or "Bilel",
                    "category": t.product.category or "Général",
                    "purchase_price": t.product.purchase_price or 0.0,
                    "sell_price": t.product.sell_price or 0.0,
                    "fast_panel": bool(t.product.fast_panel),
                    "qty_transferred": 0,
                    "qty_sold": 0,
                    "qty_remaining": 0,
                    "revenue_generated": 0.0,
                    "profit_generated": 0.0,
                }
            prod_map[pid]["qty_transferred"] += t.quantity

        # Aggregate current stock
        for ss in seller_stocks:
            if not ss.product:
                continue
            pid = ss.product_id
            if pid not in prod_map:
                prod_map[pid] = {
                    "product_id": pid,
                    "name_fr": ss.product.name_fr,
                    "code_article": ss.product.code_article or "",
                    "barcode": ss.product.barcode or "",
                    "buyer": ss.product.buyer or "Bilel",
                    "category": ss.product.category or "Général",
                    "purchase_price": ss.product.purchase_price or 0.0,
                    "sell_price": ss.product.sell_price or 0.0,
                    "fast_panel": bool(ss.product.fast_panel),
                    "qty_transferred": 0,
                    "qty_sold": 0,
                    "qty_remaining": 0,
                    "revenue_generated": 0.0,
                    "profit_generated": 0.0,
                }
            prod_map[pid]["qty_remaining"] += ss.quantity

        # Aggregate sales
        for s in sales:
            for it in s.items:
                pid = it.product_id
                if not it.product:
                    continue
                if pid not in prod_map:
                    prod_map[pid] = {
                        "product_id": pid,
                        "name_fr": it.product.name_fr,
                        "code_article": it.product.code_article or "",
                        "barcode": it.product.barcode or "",
                        "buyer": it.product.buyer or "Bilel",
                        "category": it.product.category or "Général",
                        "purchase_price": it.product.purchase_price or 0.0,
                        "sell_price": it.product.sell_price or 0.0,
                        "fast_panel": bool(it.product.fast_panel),
                        "qty_transferred": 0,
                        "qty_sold": 0,
                        "qty_remaining": 0,
                        "revenue_generated": 0.0,
                        "profit_generated": 0.0,
                    }
                prod_map[pid]["qty_sold"] += it.quantity
                prod_map[pid]["revenue_generated"] += (it.unit_price * it.quantity)
                prod_map[pid]["profit_generated"] += ((it.unit_price - it.purchase_price) * it.quantity)

        items_list = []
        u_capital_sent = 0.0
        u_revenue = sum(s.total for s in sales)
        u_profit = sum(sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items) for s in sales)
        u_capital_remaining = 0.0
        u_sell_value_remaining = 0.0
        u_units_sent = 0
        u_units_sold = 0
        u_units_remaining = 0

        for pid, item in prod_map.items():
            handled = item["qty_sold"] + item["qty_remaining"]
            if item["qty_transferred"] < handled:
                item["qty_transferred"] = handled

            pa = item["purchase_price"]
            pv = item["sell_price"]
            cap_sent = item["qty_transferred"] * pa
            cap_rem = item["qty_remaining"] * pa
            sell_rem = item["qty_remaining"] * pv
            ecoul = round((item["qty_sold"] / item["qty_transferred"] * 100), 1) if item["qty_transferred"] > 0 else 0.0

            item["capital_sent"] = cap_sent
            item["capital_remaining"] = cap_rem
            item["sell_value_remaining"] = sell_rem
            item["ecoulement_pct"] = ecoul

            u_capital_sent += cap_sent
            u_capital_remaining += cap_rem
            u_sell_value_remaining += sell_rem
            u_units_sent += item["qty_transferred"]
            u_units_sold += item["qty_sold"]
            u_units_remaining += item["qty_remaining"]

            items_list.append(item)

        items_list.sort(key=lambda x: (-x["qty_sold"], x["code_article"], x["name_fr"]))

        u_ecoulement = round((u_units_sold / u_units_sent * 100), 1) if u_units_sent > 0 else 0.0
        u_margin_rate = round((u_profit / u_revenue * 100), 1) if u_revenue > 0 else 0.0

        seller_data = {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at,
            "total_sales_count": len(sales),
            "capital_sent": round(u_capital_sent, 2),
            "revenue": round(u_revenue, 2),
            "profit": round(u_profit, 2),
            "margin_rate": u_margin_rate,
            "capital_remaining": round(u_capital_remaining, 2),
            "sell_value_remaining": round(u_sell_value_remaining, 2),
            "units_sent": u_units_sent,
            "units_sold": u_units_sold,
            "units_remaining": u_units_remaining,
            "ecoulement_pct": u_ecoulement,
            "items_count": len(items_list),
            "items": items_list,
        }

        sellers_progress.append(seller_data)

        grand_capital_sent += u_capital_sent
        grand_revenue += u_revenue
        grand_profit += u_profit
        grand_capital_remaining += u_capital_remaining
        grand_sell_value_remaining += u_sell_value_remaining
        grand_units_sent += u_units_sent
        grand_units_sold += u_units_sold
        grand_units_remaining += u_units_remaining

    global_ecoulement = round((grand_units_sold / grand_units_sent * 100), 1) if grand_units_sent > 0 else 0.0
    global_margin = round((grand_profit / grand_revenue * 100), 1) if grand_revenue > 0 else 0.0

    return {
        "summary": {
            "total_sellers": len(sellers_progress),
            "total_capital_sent": round(grand_capital_sent, 2),
            "total_revenue": round(grand_revenue, 2),
            "total_profit": round(grand_profit, 2),
            "total_capital_remaining": round(grand_capital_remaining, 2),
            "total_sell_value_remaining": round(grand_sell_value_remaining, 2),
            "total_units_sent": grand_units_sent,
            "total_units_sold": grand_units_sold,
            "total_units_remaining": grand_units_remaining,
            "global_ecoulement_pct": global_ecoulement,
            "global_margin_rate": global_margin,
        },
        "sellers": sellers_progress
    }

@router.post("", status_code=201)
def create_seller(data: SellerCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Ce nom d'utilisateur existe déjà")
    user = User(username=data.username, pin_hash=pwd_ctx.hash(data.pin), role=data.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role, "created_at": user.created_at}

@router.put("/{seller_id}")
def update_seller(seller_id: int, data: SellerUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == seller_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    if data.username:
        user.username = data.username
    if data.pin:
        user.pin_hash = pwd_ctx.hash(data.pin)
    if data.role:
        user.role = data.role
    db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}

@router.post("/merge")
def merge_sellers(data: SellerMergeRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    source_user = db.query(User).filter(User.id == data.source_seller_id).first()
    target_user = db.query(User).filter(User.id == data.target_seller_id).first()
    if not source_user:
        raise HTTPException(404, f"Source user ID {data.source_seller_id} not found")
    if not target_user:
        raise HTTPException(404, f"Target user ID {data.target_seller_id} not found")
    if source_user.id == target_user.id:
        raise HTTPException(400, "Source and target users cannot be the same")

    # 1. Merge SellerStock
    source_stocks = db.query(SellerStock).filter(SellerStock.seller_id == source_user.id).all()
    merged_stock_count = 0
    moved_stock_count = 0
    for s_stock in source_stocks:
        t_stock = db.query(SellerStock).filter(
            SellerStock.seller_id == target_user.id,
            SellerStock.product_id == s_stock.product_id
        ).first()
        if t_stock:
            t_stock.quantity += (s_stock.quantity or 0)
            db.delete(s_stock)
            merged_stock_count += 1
        else:
            s_stock.seller_id = target_user.id
            moved_stock_count += 1
    db.flush()

    # 2. Update StockTransfer (transfers received by source_user -> target_user)
    transfers_received_updated = db.query(StockTransfer).filter(
        StockTransfer.seller_id == source_user.id
    ).update(
        {StockTransfer.seller_id: target_user.id},
        synchronize_session=False
    )

    # 3. Update StockTransfer (transfers made by source_user -> admin user ID 1 or target_user)
    admin_user = db.query(User).filter(User.username == "admin").first()
    admin_id = admin_user.id if admin_user else 1
    transfers_made_updated = db.query(StockTransfer).filter(
        StockTransfer.transferred_by_id == source_user.id
    ).update(
        {StockTransfer.transferred_by_id: admin_id},
        synchronize_session=False
    )

    # 4. Update Sales (sales made by source_user -> target_user)
    sales_updated = db.query(Sale).filter(
        Sale.seller_id == source_user.id
    ).update(
        {Sale.seller_id: target_user.id},
        synchronize_session=False
    )

    # 5. Delete source user
    source_username = source_user.username
    source_id = source_user.id
    db.delete(source_user)
    db.commit()

    return {
        "status": "success",
        "message": f"Compte '{source_username}' (ID {source_id}) fusionné avec succès dans '{target_user.username}' (ID {target_user.id})",
        "target_user": {
            "id": target_user.id,
            "username": target_user.username,
            "role": target_user.role
        },
        "details": {
            "merged_stock_items": merged_stock_count,
            "moved_stock_items": moved_stock_count,
            "transfers_received_updated": transfers_received_updated,
            "transfers_made_updated": transfers_made_updated,
            "sales_updated": sales_updated,
            "deleted_user": source_username
        }
    }

@router.delete("/{seller_id}", status_code=204)
def delete_seller(seller_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == seller_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    db.query(StockTransfer).filter(StockTransfer.seller_id == seller_id).delete(synchronize_session=False)
    db.query(StockTransfer).filter(StockTransfer.transferred_by_id == seller_id).update({StockTransfer.transferred_by_id: 1}, synchronize_session=False)
    db.query(Sale).filter(Sale.seller_id == seller_id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
