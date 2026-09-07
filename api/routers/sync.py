from typing import List, Optional
from datetime import datetime
from pathlib import Path
import json
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from db.base import get_db
from models.product import Product
from models.stock import SellerStock, GlobalStock, StockTransfer
from models.sale import Sale, SaleItem, PaymentMethod
from models.user import User, UserRole
from api.deps import require_seller, require_admin, get_current_user
from api.websocket import manager

router = APIRouter(prefix="/api/sync", tags=["sync"])

# Ensure snapshot directory exists
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "data_bons" / "snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

class OfflineSaleItem(BaseModel):
    product_id: Optional[int] = None
    code_article: Optional[str] = None
    quantity: int
    unit_price: float
    purchase_price: Optional[float] = 0.0

class OfflineSale(BaseModel):
    local_id: Optional[int] = None
    ticket_id: Optional[str] = None
    created_at: Optional[str] = None
    payment_method: str = "cash"
    discount: float = 0.0
    notes: Optional[str] = None
    is_return: bool = False
    items: List[OfflineSaleItem] = []

class PushRequest(BaseModel):
    sales: List[OfflineSale]

class SnapshotProductItem(BaseModel):
    code_article: Optional[str] = None
    barcode: Optional[str] = None
    name_fr: Optional[str] = None
    category: Optional[str] = None
    stock_qty: int = 0
    sell_price: Optional[float] = None
    purchase_price: Optional[float] = None
    id_rapid: Optional[str] = None
    fast_panel: Optional[bool] = False

class ProgressSnapshotRequest(BaseModel):
    seller: str  # "houari", "bilel", "abdrahman"
    synced_at: Optional[str] = None
    products: List[SnapshotProductItem] = []
    sales: List[OfflineSale] = []
    total_items: Optional[int] = 0
    total_units: Optional[int] = 0
    total_capital: Optional[float] = 0.0


def is_seller_match(canonical_buyer: str, username: str) -> bool:
    b = (canonical_buyer or "").lower()
    u = (username or "").lower()
    if "hou" in b and "hou" in u: return True
    if "bil" in b and "bil" in u: return True
    if "abd" in b and "abd" in u: return True
    return False


def resolve_canonical_seller(raw_name: str):
    k = (raw_name or "").lower().strip()
    if "hou" in k:
        return "Houari", "houarii"
    elif "abd" in k:
        return "Abdrahman", "abderahman"
    return "Bilel", "bilel"


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
            try:
                sale_time = datetime.fromisoformat(osale.created_at) if osale.created_at else datetime.utcnow()
            except Exception:
                sale_time = datetime.utcnow()

            total = sum(item.quantity * item.unit_price for item in osale.items) - osale.discount

            pm = PaymentMethod.cash
            if osale.payment_method.lower() == "card":
                pm = PaymentMethod.card
            elif osale.payment_method.lower() == "mixed":
                pm = PaymentMethod.mixed

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

            for item in osale.items:
                product = None
                if item.product_id:
                    product = db.query(Product).filter_by(id=item.product_id).first()
                if not product and item.code_article:
                    product = db.query(Product).filter_by(code_article=item.code_article).first()

                purchase_p = product.purchase_price if product else (item.purchase_price or 0.0)

                if product:
                    si = SaleItem(
                        sale_id=sale.id,
                        product_id=product.id,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        purchase_price=purchase_p
                    )
                    db.add(si)

                    ss = db.query(SellerStock).filter_by(seller_id=seller.id, product_id=product.id).first()
                    if ss:
                        if osale.is_return:
                            ss.quantity += item.quantity
                        else:
                            ss.quantity = max(0, ss.quantity - item.quantity)

            db.commit()
            if osale.local_id:
                synced_local_ids.append(osale.local_id)

            await manager.broadcast_admin("sale.created", {
                "seller_name": seller.username,
                "total": total,
                "product_count": len(osale.items),
                "sale_id": sale.id,
                "is_offline_sync": True
            })

        except Exception as e:
            db.rollback()
            print(f"[SYNC ERROR] Sale {osale.local_id or osale.ticket_id}: {e}")

    return {
        "status": "success",
        "synced_ids": synced_local_ids
    }


@router.post("/progress-snapshot")
async def receive_progress_snapshot(
    data: ProgressSnapshotRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Receives 6-hour progress snapshot from local Electron POS app.
    Updates SellerStock on Render cloud atomically and stores snapshot metadata.
    Does NOT overwrite local POS prices (one-way upload from POS to Cloud).
    """
    canonical_name, canonical_username = resolve_canonical_seller(data.seller)

    # Find or verify the target user
    target_user = None
    all_users = db.query(User).all()
    for u in all_users:
        if is_seller_match(canonical_name, u.username):
            target_user = u
            break
    if not target_user:
        target_user = current_user

    other_user_ids = [u.id for u in all_users if u.id != target_user.id]

    updated_count = 0
    total_qty = 0
    total_cap = 0.0

    sync_time_str = data.synced_at or datetime.utcnow().isoformat()

    db_prods = db.query(Product).all()
    code_map = {}
    barcode_map = {}
    name_map = {}
    for p in db_prods:
        c = (p.code_article or "").strip().upper()
        if c: code_map[c] = p
        b = (p.barcode or "").strip().upper()
        if b and len(b) >= 6: barcode_map[b] = p
        n = (p.name_fr or "").strip().upper()
        if n: name_map[n] = p

    for item in data.products:
        p = None
        item_code = (item.code_article or "").strip().upper()
        item_bar = (item.barcode or "").strip().upper()
        item_name = (item.name_fr or "").strip().upper()

        if item_code and item_code in code_map:
            p = code_map[item_code]
        elif item_bar and item_bar in barcode_map:
            p = barcode_map[item_bar]
        elif item_name and item_name in name_map:
            p = name_map[item_name]

        is_divers = (
            item_code.startswith("ART-DIVERS") or
            item_bar.startswith("DIVERS") or
            (item.category or "").strip().lower() == "divers" or
            item.stock_qty >= 100000
        )

        if not p:
            p = Product(
                code_article=item.code_article or f"ART-{canonical_name[:3].upper()}-{datetime.utcnow().strftime('%M%S%f')}",
                barcode=item.barcode or "",
                name_fr=item.name_fr or "Produit Nouveau",
                category=item.category or "Général",
                purchase_price=item.purchase_price or 0.0,
                sell_price=item.sell_price or 0.0,
                buyer=canonical_name,
                fast_panel=bool(item.fast_panel)
            )
            db.add(p)
            db.flush()
            gs = GlobalStock(product_id=p.id, quantity=item.stock_qty)
            db.add(gs)
        else:
            if p.buyer != canonical_name:
                p.buyer = canonical_name
            if item.sell_price and item.sell_price > 0:
                p.sell_price = item.sell_price
            if item.fast_panel:
                p.fast_panel = True

        ss = db.query(SellerStock).filter_by(seller_id=target_user.id, product_id=p.id).first()
        if ss:
            ss.quantity = item.stock_qty
        else:
            ss = SellerStock(seller_id=target_user.id, product_id=p.id, quantity=item.stock_qty)
            db.add(ss)

        # Clear erroneous duplicates in other sellers
        if other_user_ids and not is_divers:
            other_stocks = db.query(SellerStock).filter(
                SellerStock.product_id == p.id,
                SellerStock.seller_id.in_(other_user_ids)
            ).all()
            for os_item in other_stocks:
                os_item.quantity = 0

        # Only accumulate real physical items into KPIs
        if not is_divers:
            updated_count += 1
            total_qty += item.stock_qty
            total_cap += (item.stock_qty * (item.purchase_price or p.purchase_price or 0.0))

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[SNAPSHOT DB ERROR]: {e}")

    sales_synced = 0
    if data.sales:
        for osale in data.sales:
            try:
                sale_time = datetime.fromisoformat(osale.created_at) if osale.created_at else datetime.utcnow()
                total = sum(it.quantity * it.unit_price for it in osale.items) - osale.discount
                pm = PaymentMethod.card if osale.payment_method.lower() == "card" else PaymentMethod.cash

                sale = Sale(
                    seller_id=target_user.id,
                    total=max(0.0, total),
                    discount=osale.discount,
                    payment_method=pm,
                    is_return=osale.is_return,
                    notes=osale.notes or "Synchronisation 6h Caisse",
                    created_at=sale_time
                )
                db.add(sale)
                db.flush()
                for sit in osale.items:
                    sprod = db.query(Product).filter_by(id=sit.product_id).first() if sit.product_id else None
                    if not sprod and sit.code_article:
                        sprod = db.query(Product).filter_by(code_article=sit.code_article).first()
                    si = SaleItem(
                        sale_id=sale.id,
                        product_id=sprod.id if sprod else p.id,
                        quantity=sit.quantity,
                        unit_price=sit.unit_price,
                        purchase_price=sprod.purchase_price if sprod else 0.0
                    )
                    db.add(si)
                db.commit()
                sales_synced += 1
            except Exception as se:
                db.rollback()

    snapshot_meta = {
        "seller": canonical_name,
        "username": target_user.username,
        "synced_at": sync_time_str,
        "total_items": updated_count,
        "total_units": total_qty,
        "total_capital": round(total_cap, 2),
        "sales_synced": sales_synced
    }
    snap_file = SNAPSHOTS_DIR / f"{canonical_name.lower()}_latest.json"
    try:
        with open(snap_file, "w", encoding="utf-8") as f:
            json.dump(snapshot_meta, f, ensure_ascii=False, indent=2)
    except Exception as fe:
        print(f"[WARN] Could not write snapshot file: {fe}")

    try:
        await manager.broadcast_admin("snapshot.received", snapshot_meta)
    except Exception:
        pass

    return {
        "status": "success",
        "seller": canonical_name,
        "username": target_user.username,
        "updated_products": updated_count,
        "total_units": total_qty,
        "total_capital": round(total_cap, 2),
        "synced_at": sync_time_str
    }


@router.get("/stock-capital-summary")
def get_stock_capital_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """
    Returns full metrics and product-by-product remaining stock and capital
    for the '/admin/stock-capital' web page.
    Filters out virtual/free-price items (ART-DIVERS) from physical inventory KPIs.
    """
    sellers_canonical = ["Bilel", "Abdrahman", "Houari"]
    sellers_data = {}

    for sname in sellers_canonical:
        snap_file = SNAPSHOTS_DIR / f"{sname.lower()}_latest.json"
        meta = {}
        if snap_file.exists():
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass
        
        sellers_data[sname] = {
            "name": sname,
            "username": meta.get("username", sname.lower()),
            "last_synced_at": meta.get("synced_at"),
            "items_count": 0,
            "units_remaining": 0,
            "capital_remaining": 0.0,
            "sell_value_remaining": 0.0,
            "units_sold": 0,
            "revenue": 0.0,
            "profit": 0.0,
        }

    products = db.query(Product).options(
        joinedload(Product.seller_stock).joinedload(SellerStock.seller),
        joinedload(Product.global_stock)
    ).all()

    items_list = []
    grand_capital_remaining = 0.0
    grand_units_remaining = 0
    grand_sell_value_remaining = 0.0

    for p in products:
        code = str(p.code_article or "").strip().upper()
        bar = str(p.barcode or "").strip().upper()
        cat = str(p.category or "").strip().lower()

        # Strict exclusion of virtual Article Divers with 999,999 units
        is_divers = (
            code.startswith("ART-DIVERS") or
            bar.startswith("DIVERS") or
            cat == "divers"
        )
        if is_divers:
            continue

        b_clean = (p.buyer or "Bilel").strip().capitalize()
        if "Hou" in b_clean:
            b_name = "Houari"
        elif "Abd" in b_clean:
            b_name = "Abdrahman"
        else:
            b_name = "Bilel"

        # Determine seller stock quantity with flexible matching (handles abderahman & abdrahman)
        qty = 0
        target_s = sellers_data.get(b_name)
        if p.seller_stock:
            for ss in p.seller_stock:
                if ss.seller and is_seller_match(b_name, ss.seller.username):
                    qty = ss.quantity
                    break
        if qty == 0 and p.global_stock:
            qty = p.global_stock.quantity

        # Safety: ignore any artificial runaway quantities
        if qty >= 100000:
            qty = 0

        pa = p.purchase_price or 0.0
        pv = p.sell_price or 0.0
        cap_rem = qty * pa
        sell_val_rem = qty * pv
        margin_pct = round(((pv - pa) / pa * 100), 1) if pa > 0 else 0.0

        status = "in_stock"
        if qty == 0:
            status = "out_of_stock"
        elif qty <= (p.min_quantity or 5):
            status = "low_stock"

        if target_s:
            target_s["items_count"] += 1
            target_s["units_remaining"] += qty
            target_s["capital_remaining"] += cap_rem
            target_s["sell_value_remaining"] += sell_val_rem

        grand_capital_remaining += cap_rem
        grand_units_remaining += qty
        grand_sell_value_remaining += sell_val_rem

        id_rapid = None
        if len(str(p.code_article or '')) == 4 and str(p.code_article).isdigit():
            id_rapid = str(p.code_article)

        items_list.append({
            "id": p.id,
            "code_article": p.code_article or "—",
            "barcode": p.barcode or "",
            "id_rapid": id_rapid,
            "name_fr": p.name_fr or "—",
            "category": p.category or "Général",
            "buyer": b_name,
            "purchase_price": pa,
            "sell_price": pv,
            "margin_pct": margin_pct,
            "quantity_remaining": qty,
            "capital_remaining": round(cap_rem, 2),
            "sell_value_remaining": round(sell_val_rem, 2),
            "status": status,
            "fast_panel": bool(p.fast_panel)
        })

    items_list.sort(key=lambda x: (0 if x["status"] == "out_of_stock" else (1 if x["status"] == "low_stock" else 2), -x["capital_remaining"]))

    # Sales aggregation for each seller
    sales = db.query(Sale).options(joinedload(Sale.items), joinedload(Sale.seller)).filter(Sale.is_return == False).all()
    grand_revenue = 0.0
    grand_profit = 0.0

    for s in sales:
        s_uname = (s.seller.username if s.seller else "").lower()
        s_target = "Bilel"
        if "hou" in s_uname: s_target = "Houari"
        elif "abd" in s_uname: s_target = "Abdrahman"

        s_rev = s.total or 0.0
        s_prof = sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items)
        s_units = sum(si.quantity for si in s.items)

        if s_target in sellers_data:
            sellers_data[s_target]["revenue"] += s_rev
            sellers_data[s_target]["profit"] += s_prof
            sellers_data[s_target]["units_sold"] += s_units

        grand_revenue += s_rev
        grand_profit += s_prof

    for s in sellers_data.values():
        s["capital_remaining"] = round(s["capital_remaining"], 2)
        s["sell_value_remaining"] = round(s["sell_value_remaining"], 2)
        s["revenue"] = round(s["revenue"], 2)
        s["profit"] = round(s["profit"], 2)

    return {
        "summary": {
            "total_capital_remaining": round(grand_capital_remaining, 2),
            "total_units_remaining": grand_units_remaining,
            "total_sell_value_remaining": round(grand_sell_value_remaining, 2),
            "total_revenue": round(grand_revenue, 2),
            "total_profit": round(grand_profit, 2),
            "total_products_count": len(items_list)
        },
        "sellers": list(sellers_data.values()),
        "items": items_list
    }
