from typing import Optional
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel, validator
from db.base import get_db
from models.product import Product
from models.stock import GlobalStock, SellerStock, StockTransfer
from models.user import User, UserRole
from api.deps import require_admin, require_seller
from api.websocket import manager

router = APIRouter(prefix="/api/stock", tags=["stock"])

class TransferAllByBuyerRequest(BaseModel):
    buyer: str
    seller_id: int
    notes: Optional[str] = None


class TransferItem(BaseModel):
    product_id: int
    quantity: int

    @validator("quantity")
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

class BatchTransferRequest(BaseModel):
    seller_id: int
    items: list[TransferItem]
    notes: Optional[str] = None

class TransferRequest(BaseModel):
    product_id: int
    seller_id: int
    quantity: int

    @validator("quantity")
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

class StockAddRequest(BaseModel):
    quantity: int

    @validator("quantity")
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

@router.get("/global")
def get_global_stock(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    stocks = db.query(GlobalStock).options(joinedload(GlobalStock.product)).all()
    return [{
        "product_id": gs.product_id,
        "name_fr": gs.product.name_fr if gs.product else "—",
        "barcode": gs.product.barcode if gs.product else "",
        "code_article": gs.product.code_article if gs.product else "",
        "category": (gs.product.category if gs.product else "") or "Général",
        "sell_price": gs.product.sell_price if gs.product else 0.0,
        "purchase_price": gs.product.purchase_price if gs.product else 0.0,
        "buyer": (gs.product.buyer if gs.product else "Bilal") or "Bilal",
        "quantity": gs.quantity,
        "min_quantity": gs.product.min_quantity if gs.product else 5,
        "low_stock": gs.quantity <= (gs.product.min_quantity if gs.product else 5),
    } for gs in stocks]

@router.get("/by-buyer-summary")
@router.get("/capital-overview")
def get_stock_capital_overview(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Complete breakdown of remaining capital across global reserve and sellers."""
    global_stocks = db.query(GlobalStock).options(joinedload(GlobalStock.product)).all()
    seller_stocks = db.query(SellerStock).options(joinedload(SellerStock.product), joinedload(SellerStock.seller)).all()
    
    def canonical_buyer(buyer_str):
        b = (buyer_str or "Bilal").strip().lower()
        if b in ["bilel", "bilal"]:
            return "Bilel"
        elif b == "houari":
            return "Houari"
        elif "abd" in b or "rahman" in b:
            return "Abdrahman"
        return "Autre"

    summary = {
        "total": {
            "reserve_capital": 0.0, "seller_capital": 0.0, "total_capital": 0.0,
            "reserve_units": 0, "seller_units": 0, "total_units": 0,
            "total_sell_value": 0.0
        },
        "Bilel": {
            "reserve_capital": 0.0, "seller_capital": 0.0, "total_capital": 0.0,
            "reserve_units": 0, "seller_units": 0, "total_units": 0,
            "product_count": 0, "total_sell_value": 0.0
        },
        "Abdrahman": {
            "reserve_capital": 0.0, "seller_capital": 0.0, "total_capital": 0.0,
            "reserve_units": 0, "seller_units": 0, "total_units": 0,
            "product_count": 0, "total_sell_value": 0.0
        },
        "Houari": {
            "reserve_capital": 0.0, "seller_capital": 0.0, "total_capital": 0.0,
            "reserve_units": 0, "seller_units": 0, "total_units": 0,
            "product_count": 0, "total_sell_value": 0.0
        }
    }

    # 1. Global Stock
    for gs in global_stocks:
        p = gs.product
        if not p:
            continue
        can = canonical_buyer(p.buyer)
        if can not in summary:
            summary[can] = {"reserve_capital": 0.0, "seller_capital": 0.0, "total_capital": 0.0, "reserve_units": 0, "seller_units": 0, "total_units": 0, "product_count": 0, "total_sell_value": 0.0}
        qty = gs.quantity or 0
        pa = p.purchase_price or 0.0
        pv = p.sell_price or 0.0
        cap = qty * pa
        sell_val = qty * pv

        summary[can]["product_count"] += 1
        summary[can]["reserve_units"] += qty
        summary[can]["total_units"] += qty
        summary[can]["reserve_capital"] += cap
        summary[can]["total_capital"] += cap
        summary[can]["total_sell_value"] += sell_val

        summary["total"]["reserve_units"] += qty
        summary["total"]["total_units"] += qty
        summary["total"]["reserve_capital"] += cap
        summary["total"]["total_capital"] += cap
        summary["total"]["total_sell_value"] += sell_val

    # 2. Seller Stock
    for ss in seller_stocks:
        p = ss.product
        if not p:
            continue
        can = canonical_buyer(p.buyer)
        if can not in summary:
            summary[can] = {"reserve_capital": 0.0, "seller_capital": 0.0, "total_capital": 0.0, "reserve_units": 0, "seller_units": 0, "total_units": 0, "product_count": 0, "total_sell_value": 0.0}
        qty = ss.quantity or 0
        pa = p.purchase_price or 0.0
        pv = p.sell_price or 0.0
        cap = qty * pa
        sell_val = qty * pv

        summary[can]["seller_units"] += qty
        summary[can]["total_units"] += qty
        summary[can]["seller_capital"] += cap
        summary[can]["total_capital"] += cap
        summary[can]["total_sell_value"] += sell_val

        summary["total"]["seller_units"] += qty
        summary["total"]["total_units"] += qty
        summary["total"]["seller_capital"] += cap
        summary["total"]["total_capital"] += cap
        summary["total"]["total_sell_value"] += sell_val

    return summary


@router.post("/global/{product_id}/add")
def add_global_stock(product_id: int, data: StockAddRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    gs = db.query(GlobalStock).with_for_update().filter_by(product_id=product_id).first()
    if not gs:
        raise HTTPException(404, "Produit introuvable")
    gs.quantity += data.quantity
    db.commit()
    return {"product_id": product_id, "new_quantity": gs.quantity}

@router.post("/transfer")
async def transfer_stock(data: TransferRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # Validate seller exists
    seller = db.query(User).filter(User.id == data.seller_id).first()
    if not seller:
        raise HTTPException(404, "Vendeur introuvable")

    product = db.query(Product).filter(Product.id == data.product_id).first()
    if not product:
        raise HTTPException(404, "Produit introuvable")

    # ATOMIC transaction
    gs = db.query(GlobalStock).with_for_update().filter_by(product_id=data.product_id).first()
    if not gs or gs.quantity < data.quantity:
        raise HTTPException(400, f"Stock global insuffisant (disponible: {gs.quantity if gs else 0})")

    gs.quantity -= data.quantity

    ss = db.query(SellerStock).with_for_update().filter_by(seller_id=data.seller_id, product_id=data.product_id).first()
    if ss:
        ss.quantity += data.quantity
    else:
        ss = SellerStock(seller_id=data.seller_id, product_id=data.product_id, quantity=data.quantity)
        db.add(ss)

    transfer = StockTransfer(
        product_id=data.product_id, seller_id=data.seller_id,
        transferred_by_id=admin.id, quantity=data.quantity
    )
    db.add(transfer)
    db.commit()

    await manager.broadcast_admin("stock.transfer", {
        "seller_name": seller.username,
        "product_name": product.name_fr,
        "quantity": data.quantity,
    })
    await manager.broadcast_seller(data.seller_id, "stock.updated", {
        "product_id": data.product_id,
        "new_quantity": ss.quantity,
    })

    return {"detail": "Transfert effectué", "seller": seller.username, "product": product.name_fr, "quantity": data.quantity}

@router.post("/transfer-batch")
async def transfer_stock_batch(data: BatchTransferRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    seller = db.query(User).filter(User.id == data.seller_id).first()
    if not seller:
        raise HTTPException(404, "Vendeur introuvable")

    if not data.items:
        raise HTTPException(400, "Aucun produit sélectionné pour le transfert")

    transferred_items = []
    total_val = 0.0

    # Process all in one transaction
    for it in data.items:
        product = db.query(Product).filter(Product.id == it.product_id).first()
        if not product:
            raise HTTPException(404, f"Produit ID {it.product_id} introuvable")

        gs = db.query(GlobalStock).with_for_update().filter_by(product_id=it.product_id).first()
        if not gs or gs.quantity < it.quantity:
            raise HTTPException(400, f"Stock global insuffisant pour '{product.name_fr}' (disponible: {gs.quantity if gs else 0})")

        gs.quantity -= it.quantity

        ss = db.query(SellerStock).with_for_update().filter_by(seller_id=data.seller_id, product_id=it.product_id).first()
        if ss:
            ss.quantity += it.quantity
        else:
            ss = SellerStock(seller_id=data.seller_id, product_id=it.product_id, quantity=it.quantity)
            db.add(ss)

        transfer = StockTransfer(
            product_id=it.product_id,
            seller_id=data.seller_id,
            transferred_by_id=admin.id,
            quantity=it.quantity
        )
        db.add(transfer)

        item_total = it.quantity * product.sell_price
        total_val += item_total
        transferred_items.append({
            "product_id": product.id,
            "code_article": product.code_article,
            "barcode": product.barcode,
            "name_fr": product.name_fr,
            "quantity": it.quantity,
            "sell_price": product.sell_price,
            "total_value": item_total
        })

    db.commit()

    # WebSocket events
    for it in transferred_items:
        await manager.broadcast_seller(data.seller_id, "stock.updated", {
            "product_id": it["product_id"],
            "new_quantity": it["quantity"]
        })

    await manager.broadcast_admin("stock.transfer", {
        "seller_name": seller.username,
        "product_name": f"{len(transferred_items)} produits (Lot)",
        "quantity": sum(it["quantity"] for it in transferred_items)
    })

    return {
        "status": "success",
        "transfer_date": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "seller_name": seller.username,
        "admin_name": admin.username,
        "notes": data.notes,
        "items": transferred_items,
        "total_items_count": sum(it["quantity"] for it in transferred_items),
        "total_value": total_val
    }

@router.get("/seller/{seller_id}")
def get_seller_stock(seller_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    stocks = db.query(SellerStock).filter_by(seller_id=seller_id).all()
    return [{
        "product_id": ss.product_id,
        "name_fr": ss.product.name_fr,
        "barcode": ss.product.barcode,
        "sell_price": ss.product.sell_price,
        "quantity": ss.quantity,
    } for ss in stocks]

@router.get("/me")
def get_my_stock(db: Session = Depends(get_db), seller: User = Depends(require_seller)):
    stocks = db.query(SellerStock).filter_by(seller_id=seller.id).all()
    return [{
        "product_id": ss.product_id,
        "name_fr": ss.product.name_fr,
        "barcode": ss.product.barcode,
        "sell_price": ss.product.sell_price,
        "quantity": ss.quantity,
    } for ss in stocks]

@router.post("/transfer-by-buyer")
async def transfer_stock_by_buyer(data: TransferAllByBuyerRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    seller = db.query(User).filter(User.id == data.seller_id).first()
    if not seller:
        raise HTTPException(404, "Vendeur introuvable")

    buyer_name = (data.buyer or "").strip()
    b_lower = buyer_name.lower()
    if b_lower in ["bilel", "bilal"]:
        buyer_filter = func.lower(Product.buyer).in_(["bilel", "bilal"])
        canonical_buyer = "Bilel"
    elif b_lower == "houari":
        buyer_filter = (func.lower(Product.buyer) == "houari")
        canonical_buyer = "Houari"
    elif b_lower in ["abdrahman", "abderrahmane", "bouderouaz"]:
        buyer_filter = func.lower(Product.buyer).in_(["abdrahman", "abderrahmane", "bouderouaz"])
        canonical_buyer = "Abdrahman"
    else:
        buyer_filter = (func.lower(Product.buyer) == b_lower)
        canonical_buyer = buyer_name

    stocks = db.query(GlobalStock).join(Product, Product.id == GlobalStock.product_id)\
               .options(joinedload(GlobalStock.product))\
               .filter(buyer_filter, GlobalStock.quantity > 0).all()

    if not stocks:
        raise HTTPException(400, f"Aucun stock global disponible (> 0) à transférer pour le gérant '{canonical_buyer}'")

    prod_ids = [gs.product_id for gs in stocks]
    existing_seller_stocks = {
        ss.product_id: ss
        for ss in db.query(SellerStock).filter(
            SellerStock.seller_id == data.seller_id,
            SellerStock.product_id.in_(prod_ids)
        ).all()
    }

    now = datetime.datetime.utcnow()
    transferred_count = 0
    total_units = 0
    total_capital = 0.0
    total_sell_val = 0.0
    new_seller_stocks = []
    transfers_to_insert = []

    for gs in stocks:
        product = gs.product
        qty = gs.quantity
        if qty <= 0:
            continue

        # 100% of available stock is transferred
        gs.quantity = 0

        if gs.product_id in existing_seller_stocks:
            existing_seller_stocks[gs.product_id].quantity += qty
        else:
            ss = SellerStock(seller_id=data.seller_id, product_id=gs.product_id, quantity=qty)
            new_seller_stocks.append(ss)
            existing_seller_stocks[gs.product_id] = ss

        transfers_to_insert.append(StockTransfer(
            product_id=gs.product_id,
            seller_id=data.seller_id,
            transferred_by_id=admin.id,
            quantity=qty,
            created_at=now
        ))

        transferred_count += 1
        total_units += qty
        pa = product.purchase_price or 0.0 if product else 0.0
        pv = product.sell_price or 0.0 if product else 0.0
        total_capital += qty * pa
        total_sell_val += qty * pv

    if new_seller_stocks:
        db.bulk_save_objects(new_seller_stocks)
    if transfers_to_insert:
        db.bulk_save_objects(transfers_to_insert)

    db.commit()

    # WebSocket events
    try:
        await manager.broadcast_admin("stock.transfer", {
            "seller_name": seller.username,
            "product_name": f"Capital {canonical_buyer} ({transferred_count} articles)",
            "quantity": total_units,
        })
        await manager.broadcast_seller(data.seller_id, "stock.updated_all", {
            "seller_id": data.seller_id,
            "items_count": transferred_count,
            "units_count": total_units
        })
    except Exception:
        pass

    return {
        "status": "success",
        "buyer": canonical_buyer,
        "seller_name": seller.username,
        "seller_id": seller.id,
        "transferred_products": transferred_count,
        "total_units": total_units,
        "total_capital_da": round(total_capital, 2),
        "total_sell_val_da": round(total_sell_val, 2),
        "message": f"Transfert complet réussi : {transferred_count} articles ({total_units:,} unités, {total_capital:,.2f} DA) de {canonical_buyer} transférés vers le vendeur {seller.username}."
    }

@router.get("/transfers")
def get_all_transfers(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    transfers = db.query(StockTransfer)\
                  .options(
                      joinedload(StockTransfer.product),
                      joinedload(StockTransfer.seller),
                      joinedload(StockTransfer.transferred_by)
                  )\
                  .order_by(StockTransfer.created_at.desc()).all()
    return [{
        "id": t.id,
        "created_at": t.created_at.isoformat(),
        "product_name": t.product.name_fr if t.product else "—",
        "barcode": (t.product.barcode or "") if t.product else "",
        "code_article": (t.product.code_article or "") if t.product else "",
        "sell_price": t.product.sell_price if t.product else 0.0,
        "purchase_price": t.product.purchase_price if t.product else 0.0,
        "buyer": (t.product.buyer if t.product else "Bilal") or "Bilal",
        "seller_name": t.seller.username if t.seller else "—",
        "transferred_by": t.transferred_by.username if t.transferred_by else "admin",
        "quantity": t.quantity,
    } for t in transfers]


@router.get("/transfers/seller/{seller_id}")
def get_transfers_by_seller(seller_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    transfers = db.query(StockTransfer).filter_by(seller_id=seller_id).order_by(StockTransfer.created_at.desc()).all()
    return [{
        "id": t.id,
        "created_at": t.created_at.isoformat(),
        "product_name": t.product.name_fr,
        "barcode": t.product.barcode or "",
        "code_article": t.product.code_article or "",
        "sell_price": t.product.sell_price,
        "purchase_price": t.product.purchase_price,
        "buyer": t.product.buyer or "Bilal",
        "seller_name": t.seller.username,
        "transferred_by": t.transferred_by.username,
        "quantity": t.quantity,
    } for t in transfers]


class AssignSellerStockRequest(BaseModel):
    seller_id: int
    product_ids: list[int]
    quantity: int = 5
    notes: Optional[str] = None

@router.post("/assign-seller-stock")
def assign_seller_stock(data: AssignSellerStockRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    seller = db.query(User).filter(User.id == data.seller_id).first()
    if not seller:
        raise HTTPException(404, "Vendeur introuvable")
    
    assigned = 0
    for pid in data.product_ids:
        prod = db.query(Product).filter(Product.id == pid).first()
        if not prod:
            continue
        ss = db.query(SellerStock).filter_by(seller_id=data.seller_id, product_id=pid).first()
        if ss:
            ss.quantity = max(ss.quantity, data.quantity)
        else:
            ss = SellerStock(seller_id=data.seller_id, product_id=pid, quantity=data.quantity)
            db.add(ss)
        
        # Log transfer
        transfer = StockTransfer(
            product_id=pid,
            seller_id=data.seller_id,
            transferred_by_id=admin.id,
            quantity=data.quantity
        )
        db.add(transfer)
        assigned += 1
    
    db.commit()
    return {"detail": f"{assigned} produits assignés au vendeur {seller.username}", "assigned_count": assigned}
