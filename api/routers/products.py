import random, string
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.base import get_db
from models.product import Product
from models.stock import GlobalStock, SellerStock
from models.user import User
from api.deps import require_admin, require_seller, get_current_user

router = APIRouter(prefix="/api/products", tags=["products"])

def gen_code():
    return "ART-" + "".join(random.choices(string.digits, k=6))

class ProductCreate(BaseModel):
    name_fr: str
    name_ar: Optional[str] = None
    barcode: Optional[str] = None
    code_article: Optional[str] = None
    category: Optional[str] = None
    purchase_price: float = 0.0
    sell_price: float = 0.0
    min_quantity: int = 5
    description: Optional[str] = None
    initial_quantity: int = 0

class ProductUpdate(BaseModel):
    name_fr: Optional[str] = None
    name_ar: Optional[str] = None
    barcode: Optional[str] = None
    code_article: Optional[str] = None
    category: Optional[str] = None
    purchase_price: Optional[float] = None
    sell_price: Optional[float] = None
    min_quantity: Optional[int] = None
    description: Optional[str] = None

def product_to_admin_dict(p: Product) -> dict:
    return {
        "id": p.id, "code_article": p.code_article, "barcode": p.barcode,
        "name_fr": p.name_fr, "name_ar": p.name_ar, "category": p.category,
        "purchase_price": p.purchase_price, "sell_price": p.sell_price,
        "min_quantity": p.min_quantity, "description": p.description,
        "created_at": p.created_at,
        "global_stock_quantity": p.global_stock.quantity if p.global_stock else 0,
    }

def product_to_seller_dict(p: Product, seller_qty: int) -> dict:
    return {
        "id": p.id, "code_article": p.code_article, "barcode": p.barcode,
        "name_fr": p.name_fr, "name_ar": p.name_ar, "category": p.category,
        "sell_price": p.sell_price, "min_quantity": p.min_quantity,
        "seller_stock_quantity": seller_qty,
    }

@router.get("")
def list_products(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    products = db.query(Product).all()
    return [product_to_admin_dict(p) for p in products]

@router.get("/seller")
def list_seller_products(db: Session = Depends(get_db), seller: User = Depends(require_seller)):
    stocks = db.query(SellerStock).filter(SellerStock.seller_id == seller.id, SellerStock.quantity > 0).all()
    return [product_to_seller_dict(ss.product, ss.quantity) for ss in stocks]

@router.get("/search")
def search_products(
    q: Optional[str] = None, barcode: Optional[str] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    from models.user import UserRole
    if current_user.role == UserRole.admin:
        query = db.query(Product)
        if barcode:
            p = query.filter(Product.barcode == barcode).first()
            return [product_to_admin_dict(p)] if p else []
        if q:
            query = query.filter(Product.name_fr.ilike(f"%{q}%") | Product.code_article.ilike(f"%{q}%"))
        return [product_to_admin_dict(p) for p in query.limit(20).all()]
    else:
        stocks = db.query(SellerStock).filter(SellerStock.seller_id == current_user.id, SellerStock.quantity > 0).all()
        results = []
        for ss in stocks:
            p = ss.product
            if barcode and p.barcode == barcode:
                return [product_to_seller_dict(p, ss.quantity)]
            if q and (q.lower() in p.name_fr.lower() or q in (p.code_article or "")):
                results.append(product_to_seller_dict(p, ss.quantity))
        return results[:20]

@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    return product_to_admin_dict(p)

@router.post("", status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    code = data.code_article or gen_code()
    while db.query(Product).filter(Product.code_article == code).first():
        code = gen_code()
    p = Product(
        code_article=code, barcode=data.barcode or None,
        name_fr=data.name_fr, name_ar=data.name_ar, category=data.category,
        purchase_price=data.purchase_price, sell_price=data.sell_price,
        min_quantity=data.min_quantity, description=data.description,
    )
    db.add(p)
    db.flush()
    gs = GlobalStock(product_id=p.id, quantity=data.initial_quantity)
    db.add(gs)
    db.commit()
    db.refresh(p)
    return product_to_admin_dict(p)

@router.put("/{product_id}")
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    for field, val in data.dict(exclude_none=True).items():
        setattr(p, field, val)
    db.commit()
    db.refresh(p)
    return product_to_admin_dict(p)

@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    db.delete(p)
    db.commit()
