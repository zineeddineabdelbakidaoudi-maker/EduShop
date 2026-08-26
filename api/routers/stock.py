from typing import Optional
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator
from db.base import get_db
from models.product import Product
from models.stock import GlobalStock, SellerStock, StockTransfer
from models.user import User, UserRole
from api.deps import require_admin, require_seller
from api.websocket import manager

router = APIRouter(prefix="/api/stock", tags=["stock"])

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
    stocks = db.query(GlobalStock).all()
    return [{
        "product_id": gs.product_id,
        "name_fr": gs.product.name_fr,
        "barcode": gs.product.barcode,
        "code_article": gs.product.code_article,
        "sell_price": gs.product.sell_price,
        "purchase_price": gs.product.purchase_price,
        "buyer": gs.product.buyer or "Bilal",
        "quantity": gs.quantity,
        "min_quantity": gs.product.min_quantity,
        "low_stock": gs.quantity <= gs.product.min_quantity,
    } for gs in stocks]

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
    seller = db.query(User).filter(User.id == data.seller_id, User.role == UserRole.seller).first()
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
    seller = db.query(User).filter(User.id == data.seller_id, User.role == UserRole.seller).first()
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

@router.get("/transfers")
def get_all_transfers(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    transfers = db.query(StockTransfer).order_by(StockTransfer.created_at.desc()).all()
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
