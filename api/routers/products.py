import random, string, re, io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
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

def normalize_barcodes(barcode_val: Optional[str] = None, barcodes_list: Optional[List[str]] = None) -> Optional[str]:
    codes = []
    if barcode_val:
        codes.extend(re.split(r'[,;|\s]+', str(barcode_val).strip()))
    if barcodes_list:
        for b in barcodes_list:
            if b:
                codes.extend(re.split(r'[,;|\s]+', str(b).strip()))
    
    seen = set()
    clean = []
    for c in codes:
        c_s = c.strip()
        if c_s and c_s not in seen:
            seen.add(c_s)
            clean.append(c_s)
    return ", ".join(clean[:50]) if clean else None

class ProductCreate(BaseModel):
    name_fr: str
    name_ar: Optional[str] = None
    barcode: Optional[str] = None
    barcodes: Optional[List[str]] = None
    code_article: Optional[str] = None
    category: Optional[str] = None
    purchase_price: float = 0.0
    sell_price: float = 0.0
    min_quantity: int = 5
    description: Optional[str] = None
    buyer: Optional[str] = "Bilal"
    fast_panel: Optional[bool] = False
    initial_quantity: int = 0

class ProductUpdate(BaseModel):
    name_fr: Optional[str] = None
    name_ar: Optional[str] = None
    barcode: Optional[str] = None
    barcodes: Optional[List[str]] = None
    code_article: Optional[str] = None
    category: Optional[str] = None
    purchase_price: Optional[float] = None
    sell_price: Optional[float] = None
    min_quantity: Optional[int] = None
    description: Optional[str] = None
    buyer: Optional[str] = None
    fast_panel: Optional[bool] = None

def product_to_admin_dict(p: Product) -> dict:
    return {
        "id": p.id, "code_article": p.code_article,
        "barcode": p.barcode,
        "barcodes": p.barcode_list,
        "name_fr": p.name_fr, "name_ar": p.name_ar, "category": p.category,
        "purchase_price": p.purchase_price, "sell_price": p.sell_price,
        "min_quantity": p.min_quantity, "description": p.description,
        "buyer": p.buyer or "Bilal",
        "fast_panel": bool(p.fast_panel),
        "created_at": p.created_at,
        "global_stock_quantity": p.global_stock.quantity if p.global_stock else 0,
    }

def product_to_seller_dict(p: Product, seller_qty: int) -> dict:
    return {
        "id": p.id, "code_article": p.code_article,
        "barcode": p.barcode,
        "barcodes": p.barcode_list,
        "name_fr": p.name_fr, "name_ar": p.name_ar, "category": p.category,
        "sell_price": p.sell_price, "min_quantity": p.min_quantity,
        "fast_panel": bool(p.fast_panel),
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
            bc_q = barcode.strip()
            p = query.filter(Product.barcode.ilike(f"%{bc_q}%")).first()
            return [product_to_admin_dict(p)] if p else []
        if q:
            query = query.filter(
                Product.name_fr.ilike(f"%{q}%") | 
                Product.code_article.ilike(f"%{q}%") |
                Product.barcode.ilike(f"%{q}%")
            )
        return [product_to_admin_dict(p) for p in query.limit(30).all()]
    else:
        stocks = db.query(SellerStock).filter(SellerStock.seller_id == current_user.id, SellerStock.quantity > 0).all()
        results = []
        for ss in stocks:
            p = ss.product
            if barcode:
                bc_q = barcode.strip()
                if bc_q in p.barcode_list or (p.barcode and bc_q in p.barcode):
                    return [product_to_seller_dict(p, ss.quantity)]
            if q and (q.lower() in p.name_fr.lower() or q in (p.code_article or "") or q in (p.barcode or "")):
                results.append(product_to_seller_dict(p, ss.quantity))
        return results[:30]

@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    return product_to_admin_dict(p)

@router.post("/{product_id}/toggle-fast-panel")
def toggle_fast_panel(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    p.fast_panel = not bool(p.fast_panel)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "fast_panel": p.fast_panel, "name_fr": p.name_fr}

@router.post("", status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    code = data.code_article or gen_code()
    while db.query(Product).filter(Product.code_article == code).first():
        code = gen_code()
    
    bc_clean = normalize_barcodes(data.barcode, data.barcodes)
    p = Product(
        code_article=code, barcode=bc_clean,
        name_fr=data.name_fr, name_ar=data.name_ar, category=data.category,
        purchase_price=data.purchase_price, sell_price=data.sell_price,
        min_quantity=data.min_quantity, description=data.description,
        buyer=data.buyer or "Bilal",
        fast_panel=bool(data.fast_panel)
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
    
    update_data = data.dict(exclude_unset=True)
    if "barcode" in update_data or "barcodes" in update_data:
        update_data["barcode"] = normalize_barcodes(update_data.get("barcode"), update_data.get("barcodes"))
        update_data.pop("barcodes", None)
        
    for k, v in update_data.items():
        setattr(p, k, v)
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

@router.post("/batch-import")
def batch_import_products(items: list[dict], db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Import and auto-update existing products (UPSERT) in 1 atomic transaction from JSON."""
    imported_count = 0
    updated_count = 0
    created_count = 0
    
    for it in items:
        name_fr = it.get("name_fr", "").strip()
        if not name_fr:
            continue
            
        code = it.get("code_article")
        prod_id = it.get("id")
        barcode_val = normalize_barcodes(it.get("barcode"), it.get("barcodes"))
        
        pa = float(it.get("purchase_price", 0.0))
        pv = float(it.get("sell_price", 0.0))
        if pv <= 0 and pa > 0:
            pv = round(pa * 1.25, 2)
            
        qty = int(it.get("quantity", it.get("initial_quantity", 0)))
        buyer_val = it.get("buyer") or "Houari"
        cat_val = it.get("category") or "Général"
        desc_val = it.get("description")
        is_fast = bool(it.get("fast_panel", False))
        
        # Check if product exists by: id, code_article, or (exact name_fr + same buyer)
        # KEY RULE: Same product name with DIFFERENT buyer = NEW separate product
        # (Houari and Bilel can each own the same product independently)
        existing = None
        if prod_id:
            existing = db.query(Product).filter(Product.id == int(prod_id)).first()
        if not existing and code:
            existing = db.query(Product).filter(Product.code_article == code).first()
        if not existing and name_fr:
            # Match ONLY if same name AND same buyer — different gérant = different product
            existing = db.query(Product).filter(
                Product.name_fr == name_fr,
                Product.buyer == buyer_val
            ).first()
            
        if existing:
            # ── AUTO-WRITE / UPDATE EXISTING PRODUCT ─────────────────────────
            existing.name_fr = name_fr
            if it.get("name_ar"): existing.name_ar = it.get("name_ar")
            if code: existing.code_article = code
            # Same barcode allowed across different buyers — set it freely
            if barcode_val: existing.barcode = barcode_val
            existing.category = cat_val
            existing.purchase_price = pa
            existing.sell_price = pv
            existing.buyer = buyer_val
            existing.fast_panel = is_fast
            if desc_val: existing.description = desc_val
            if "min_quantity" in it: existing.min_quantity = int(it["min_quantity"])
            
            # Update or create GlobalStock
            if existing.global_stock:
                if qty > 0:
                    existing.global_stock.quantity = qty
            else:
                db.add(GlobalStock(product_id=existing.id, quantity=qty))
                
            updated_count += 1
            imported_count += 1
        else:
            # ── CREATE NEW PRODUCT ───────────────────────────────────────────
            if not code:
                code = gen_code()
            while db.query(Product).filter(Product.code_article == code).first():
                code = gen_code()
                
            p = Product(
                code_article=code,
                barcode=barcode_val or None,
                name_fr=name_fr,
                name_ar=it.get("name_ar") or None,
                category=cat_val,
                purchase_price=pa,
                sell_price=pv,
                min_quantity=int(it.get("min_quantity", 5)),
                description=desc_val,
                buyer=buyer_val,
                fast_panel=is_fast
            )
            db.add(p)
            db.flush()
            db.add(GlobalStock(product_id=p.id, quantity=qty))
            created_count += 1
            imported_count += 1
            
    db.commit()
    return {
        "imported_count": imported_count,
        "updated_count": updated_count,
        "created_count": created_count,
        "message": f"Succès : {updated_count} produit(s) mis à jour (écrasés) et {created_count} nouveau(x) produit(s) créés."
    }

