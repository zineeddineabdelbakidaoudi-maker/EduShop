import random, string, re, io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, func
from pydantic import BaseModel
from db.base import get_db
from models.product import Product
from models.stock import GlobalStock, SellerStock
from models.user import User
from api.deps import require_admin, require_seller, get_current_user

router = APIRouter(prefix="/api/products", tags=["products"])

def gen_code():
    return "ART-" + "".join(random.choices(string.digits, k=6))


def ensure_barcode_not_unique(db: Session):
    """Removes any unique constraint/index on barcode in both SQLite and PostgreSQL."""
    drop_sqls = [
        "DROP INDEX IF EXISTS ix_products_barcode",
        "ALTER TABLE products DROP CONSTRAINT IF EXISTS uq_products_barcode",
        "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_barcode_key",
        """DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint 
                WHERE conrelid = 'products'::regclass 
                AND contype = 'u' 
                AND conname LIKE '%barcode%'
            ) LOOP
                EXECUTE 'ALTER TABLE products DROP CONSTRAINT IF EXISTS ' || quote_ident(r.conname);
            END LOOP;
        END $$;""",
        "CREATE INDEX IF NOT EXISTS ix_products_barcode ON products (barcode)",
        "CREATE INDEX IF NOT EXISTS ix_products_name_fr ON products (name_fr)",
        "CREATE INDEX IF NOT EXISTS ix_products_buyer ON products (buyer)",
        "CREATE INDEX IF NOT EXISTS ix_products_category ON products (category)",
        "CREATE INDEX IF NOT EXISTS ix_products_fast_panel ON products (fast_panel)",
        "CREATE INDEX IF NOT EXISTS ix_products_code_article ON products (code_article)"
    ]
    for s in drop_sqls:
        try:
            db.execute(text(s))
            db.commit()
        except Exception:
            db.rollback()

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

def clamp_margin_sell_price(purchase_price: Optional[float], sell_price: Optional[float]) -> Optional[float]:
    """Ensures margin is not negative (< 0%) and not over 100%. If outside [0%, 100%], reset to 60%."""
    if purchase_price and purchase_price > 0 and sell_price is not None:
        m = (sell_price - purchase_price) / purchase_price * 100.0
        if m < 0.0 or m > 100.0:
            return round(purchase_price * 1.60, 2)
        return round(sell_price, 2)
    return round(sell_price, 2) if sell_price is not None else None

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
    buyers: Optional[List[str]] = None
    fast_panel: Optional[bool] = None

from api.websocket import manager

def product_to_admin_dict(p: Product) -> dict:
    tot_stock = (p.global_stock.quantity if p.global_stock else 0)
    if hasattr(p, 'seller_stock') and p.seller_stock:
        tot_stock += sum(ss.quantity for ss in p.seller_stock if ss.quantity > 0)
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
        "global_stock_quantity": tot_stock,
        "seller_stock_quantity": tot_stock,
        "stock_qty": tot_stock,
        "quantity": tot_stock,
    }

def product_to_seller_dict(p: Product, seller_qty: int) -> dict:
    return {
        "id": p.id, "code_article": p.code_article,
        "barcode": p.barcode,
        "barcodes": p.barcode_list,
        "name_fr": p.name_fr, "name_ar": p.name_ar, "category": p.category,
        "buyer": p.buyer or "Bilal",
        "sell_price": p.sell_price, "min_quantity": p.min_quantity,
        "fast_panel": bool(p.fast_panel),
        "seller_stock_quantity": seller_qty,
        "stock_qty": seller_qty,
        "quantity": seller_qty,
        "global_stock_quantity": seller_qty,
    }

@router.get("")
def list_products(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    products = db.query(Product).options(joinedload(Product.global_stock), joinedload(Product.seller_stock)).all()
    return [product_to_admin_dict(p) for p in products]

@router.get("/seller")
def list_seller_products(
    seller_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_seller_id = seller_id or current_user.id
    target_user = db.query(User).filter(User.id == target_seller_id).first()
    uname = (target_user.username if target_user else "").lower().strip()

    stocks = (
        db.query(SellerStock)
        .options(joinedload(SellerStock.product))
        .filter(SellerStock.seller_id == target_seller_id, SellerStock.quantity > 0)
        .all()
    )

    # STRICT BUYER ISOLATION: A seller ONLY ever receives products belonging to their buyer account!
    if uname.startswith("bil"):
        stocks = [ss for ss in stocks if ss.product and (ss.product.buyer or "").lower().startswith("bil")]
    elif uname.startswith("hou"):
        stocks = [ss for ss in stocks if ss.product and (ss.product.buyer or "").lower().startswith("hou")]
    elif uname.startswith("abd"):
        stocks = [ss for ss in stocks if ss.product and (ss.product.buyer or "").lower().startswith("abd")]

    if stocks:
        return [product_to_seller_dict(ss.product, ss.quantity) for ss in stocks if ss.product]
    
    # Fallback to products belonging to this buyer with global stock:
    if uname.startswith("bil"):
        products = db.query(Product).options(joinedload(Product.global_stock)).filter(Product.buyer.ilike("bil%")).all()
        return [product_to_seller_dict(p, p.global_stock.quantity if p.global_stock else 0) for p in products]
    elif uname.startswith("hou"):
        products = db.query(Product).options(joinedload(Product.global_stock)).filter(Product.buyer.ilike("hou%")).all()
        return [product_to_seller_dict(p, p.global_stock.quantity if p.global_stock else 0) for p in products]
    elif uname.startswith("abd"):
        products = db.query(Product).options(joinedload(Product.global_stock)).filter(Product.buyer.ilike("abd%")).all()
        return [product_to_seller_dict(p, p.global_stock.quantity if p.global_stock else 0) for p in products]
    elif uname == "admin":
        products = db.query(Product).options(joinedload(Product.global_stock), joinedload(Product.seller_stock)).all()
        result = []
        for p in products:
            tot_qty = (p.global_stock.quantity if p.global_stock else 0) + sum(ss.quantity for ss in p.seller_stock if ss.quantity > 0)
            result.append(product_to_seller_dict(p, tot_qty))
        return result
    
    return []

@router.get("/search")
def search_products(
    q: Optional[str] = None, barcode: Optional[str] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    uname = (current_user.username or "").lower().strip()
    stocks = (
        db.query(SellerStock)
        .options(joinedload(SellerStock.product))
        .filter(SellerStock.seller_id == current_user.id, SellerStock.quantity > 0)
        .all()
    )

    if uname.startswith("bil"):
        stocks = [ss for ss in stocks if ss.product and (ss.product.buyer or "").lower().startswith("bil")]
    elif uname.startswith("hou"):
        stocks = [ss for ss in stocks if ss.product and (ss.product.buyer or "").lower().startswith("hou")]
    elif uname.startswith("abd"):
        stocks = [ss for ss in stocks if ss.product and (ss.product.buyer or "").lower().startswith("abd")]

    if stocks:
        results = []
        for ss in stocks:
            p = ss.product
            if not p:
                continue
            if barcode:
                bc_q = barcode.strip()
                if bc_q in p.barcode_list or (p.barcode and bc_q in p.barcode):
                    return [product_to_seller_dict(p, ss.quantity)]
            if q and (q.lower() in p.name_fr.lower() or q in (p.code_article or "") or q in (p.barcode or "")):
                results.append(product_to_seller_dict(p, ss.quantity))
        if results:
            return results[:30]

    # Fallback to catalog of this buyer:
    query = db.query(Product).options(joinedload(Product.global_stock))
    if uname.startswith("bil"):
        query = query.filter(Product.buyer.ilike("bil%"))
    elif uname.startswith("hou"):
        query = query.filter(Product.buyer.ilike("hou%"))
    elif uname.startswith("abd"):
        query = query.filter(Product.buyer.ilike("abd%"))
    elif uname != "admin":
        return []
    
    if barcode:
        bc_q = barcode.strip()
        query = query.filter(Product.barcode.ilike(f"%{bc_q}%"))
    if q:
        query = query.filter(
            Product.name_fr.ilike(f"%{q}%") | 
            Product.code_article.ilike(f"%{q}%") |
            Product.barcode.ilike(f"%{q}%")
        )
    fallback_prods = query.limit(30).all()
    res_list = []
    for p in fallback_prods:
        s_stock = db.query(SellerStock).filter(SellerStock.seller_id == current_user.id, SellerStock.product_id == p.id).first()
        qty = s_stock.quantity if s_stock and s_stock.quantity > 0 else (p.global_stock.quantity if p.global_stock else 0)
        res_list.append(product_to_seller_dict(p, qty))
    return res_list

def ensure_divers_product(db: Session, buyer: str = "Bilel") -> Product:
    b_clean = (buyer or "Bilel").strip()
    b_prefix = b_clean[:3].upper()
    code = f"ART-DIVERS-{b_prefix}"
    p = db.query(Product).filter(
        (Product.code_article == code) | 
        ((Product.category == "Divers") & (Product.buyer.ilike(f"{b_prefix}%")))
    ).first()
    if not p:
        p = Product(
            code_article=code,
            barcode=f"DIVERS_{b_prefix}",
            name_fr=f"Article Divers ({b_clean})",
            category="Divers",
            purchase_price=0.0,
            sell_price=0.0,
            buyer=b_clean,
            fast_panel=False,
            min_quantity=0,
            description="Article divers à prix libre (Raccourci +)"
        )
        db.add(p)
        db.flush()
        gs = GlobalStock(product_id=p.id, quantity=999999)
        db.add(gs)
        try:
            db.commit()
            db.refresh(p)
        except Exception:
            db.rollback()
            p = db.query(Product).filter(Product.code_article == code).first()
    return p

@router.get("/divers-item")
def get_or_create_divers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    uname = (current_user.username or "").lower().strip()
    buyer = "Bilel"
    if uname.startswith("hou"):
        buyer = "Houari"
    elif uname.startswith("abd"):
        buyer = "Abdrahman"
    p = ensure_divers_product(db, buyer)
    return {
        "id": p.id,
        "code_article": p.code_article,
        "name_fr": p.name_fr,
        "sell_price": p.sell_price,
        "category": "Divers",
        "buyer": p.buyer
    }

@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    return product_to_admin_dict(p)

@router.post("/{product_id}/toggle-fast-panel")
async def toggle_fast_panel(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    p.fast_panel = not bool(p.fast_panel)
    db.commit()
    db.refresh(p)
    try:
        await manager.broadcast_all("product.updated", {"id": p.id, "fast_panel": p.fast_panel, "buyer": p.buyer})
    except Exception:
        pass
    return {"id": p.id, "fast_panel": p.fast_panel, "name_fr": p.name_fr}

@router.post("", status_code=201)
async def create_product(data: ProductCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    code = data.code_article or gen_code()
    while db.query(Product).filter(Product.code_article == code).first():
        code = gen_code()
    
    bc_clean = normalize_barcodes(data.barcode, data.barcodes)
    safe_sell = clamp_margin_sell_price(data.purchase_price, data.sell_price)
    p = Product(
        code_article=code, barcode=bc_clean,
        name_fr=data.name_fr, name_ar=data.name_ar, category=data.category,
        purchase_price=data.purchase_price, sell_price=safe_sell,
        min_quantity=data.min_quantity, description=data.description,
        buyer=data.buyer or "Bilal",
        fast_panel=bool(data.fast_panel)
    )
    db.add(p)
    db.flush()
    gs = GlobalStock(product_id=p.id, quantity=data.initial_quantity)
    db.add(gs)
    try:
        db.commit()
        db.refresh(p)
    except Exception as e:
        db.rollback()
        ensure_barcode_not_unique(db)
        # re-add and commit
        db.add(p)
        db.flush()
        db.add(GlobalStock(product_id=p.id, quantity=data.initial_quantity))
        try:
            db.commit()
            db.refresh(p)
        except Exception as e2:
            db.rollback()
            raise HTTPException(400, f"Erreur création produit : {str(e2)}")
    try:
        await manager.broadcast_all("product.updated", {"id": p.id, "buyer": p.buyer})
    except Exception:
        pass
    return product_to_admin_dict(p)

@router.put("/{product_id}")
async def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    
    update_data = data.dict(exclude_unset=True)
    buyers = update_data.pop("buyers", None)
    if "barcode" in update_data or "barcodes" in update_data:
        update_data["barcode"] = normalize_barcodes(update_data.get("barcode"), update_data.get("barcodes"))
        update_data.pop("barcodes", None)
        
    if "sell_price" in update_data or "purchase_price" in update_data:
        p_purch = update_data.get("purchase_price", p.purchase_price)
        p_sell = update_data.get("sell_price", p.sell_price)
        safe_sell = clamp_margin_sell_price(p_purch, p_sell)
        if safe_sell is not None:
            update_data["sell_price"] = safe_sell

    for k, v in update_data.items():
        setattr(p, k, v)
    try:
        db.commit()
        db.refresh(p)
    except Exception as e:
        db.rollback()
        # Auto-heal: remove unique index/constraint on barcode and retry
        ensure_barcode_not_unique(db)
        for k, v in update_data.items():
            setattr(p, k, v)
        try:
            db.commit()
            db.refresh(p)
        except Exception as e2:
            db.rollback()
            raise HTTPException(400, f"Erreur enregistrement produit : {str(e2)}")

    # Propagate price & details to other selected buyers if specified
    if buyers and isinstance(buyers, list):
        for b in buyers:
            b_clean = str(b).strip()
            if not b_clean or (p.buyer and b_clean.lower() == p.buyer.lower()):
                continue
            
            b_prefix = b_clean[:3]
            target_prod = None
            if p.barcode:
                target_prod = db.query(Product).filter(
                    Product.buyer.ilike(f"{b_prefix}%"),
                    Product.barcode == p.barcode
                ).first()
            if not target_prod and p.name_fr:
                target_prod = db.query(Product).filter(
                    Product.buyer.ilike(f"{b_prefix}%"),
                    func.lower(Product.name_fr) == p.name_fr.lower()
                ).first()
            
            if target_prod:
                if "sell_price" in update_data and update_data["sell_price"] is not None:
                    target_prod.sell_price = update_data["sell_price"]
                if "purchase_price" in update_data and update_data["purchase_price"] is not None:
                    target_prod.purchase_price = update_data["purchase_price"]
                if "category" in update_data and update_data["category"] is not None:
                    target_prod.category = update_data["category"]
                if "barcode" in update_data and update_data["barcode"] is not None:
                    target_prod.barcode = update_data["barcode"]
                db.commit()
                try:
                    await manager.broadcast_all("product.updated", {"id": target_prod.id, "buyer": target_prod.buyer})
                except Exception:
                    pass
            else:
                new_code = gen_code()
                while db.query(Product).filter(Product.code_article == new_code).first():
                    new_code = gen_code()
                new_p = Product(
                    code_article=new_code,
                    barcode=p.barcode,
                    name_fr=p.name_fr,
                    name_ar=p.name_ar,
                    category=p.category,
                    purchase_price=p.purchase_price,
                    sell_price=p.sell_price,
                    min_quantity=p.min_quantity,
                    description=p.description,
                    buyer=b_clean,
                    fast_panel=p.fast_panel
                )
                db.add(new_p)
                db.flush()
                db.add(GlobalStock(product_id=new_p.id, quantity=0))
                try:
                    db.commit()
                    try:
                        await manager.broadcast_all("product.updated", {"id": new_p.id, "buyer": new_p.buyer})
                    except Exception:
                        pass
                except Exception:
                    db.rollback()

    try:
        await manager.broadcast_all("product.updated", {"id": p.id, "buyer": p.buyer})
    except Exception:
        pass
    return product_to_admin_dict(p)

@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Produit introuvable")
    db.delete(p)
    db.commit()
    try:
        await manager.broadcast_all("product.deleted", {"id": product_id})
    except Exception:
        pass

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
        pv = clamp_margin_sell_price(pa, pv) or pv
            
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

@router.post("/sync-matched-barcodes")
def sync_matched_barcodes(target: Optional[str] = "all", db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Automatically copies barcodes from existing products to matching unbarcoded products (Bilel, Abdrahman, etc.)."""
    ensure_barcode_not_unique(db)
    
    # Match against ANY existing catalog product with a barcode
    source_prods = db.query(Product).filter(
        Product.barcode.isnot(None), 
        Product.barcode != ""
    ).all()
    
    def norm_str(s):
        return re.sub(r'[^A-Z0-9]', '', (s or '').upper())
    
    source_map = {}
    for sp in source_prods:
        if sp.barcode and sp.barcode.strip():
            k = norm_str(sp.name_fr)
            if k and k not in source_map:
                source_map[k] = sp.barcode.strip()
            
    # Find all unbarcoded products
    target_prods = db.query(Product).filter(
        (Product.barcode.is_(None)) | (Product.barcode == "")
    ).all()
    
    synced = []
    t_filter = (target or "all").lower().strip()

    for tp in target_prods:
        b_low = (tp.buyer or "Bilal").lower().strip()
        if t_filter != "all":
            if t_filter in ["bilel", "bilal"] and b_low not in ["bilel", "bilal"]:
                continue
            elif (t_filter.startswith("abd") or t_filter.startswith("abder")) and not ("abd" in b_low or "rahman" in b_low):
                continue

        tn = norm_str(tp.name_fr)
        matched_bc = None
        for sn, sbc in source_map.items():
            if tn == sn or (len(tn) >= 8 and len(sn) >= 8 and (tn in sn or sn in tn)):
                matched_bc = sbc
                break
        
        if matched_bc:
            tp.barcode = matched_bc
            synced.append({
                "id": tp.id,
                "code_article": tp.code_article,
                "name_fr": tp.name_fr,
                "buyer": tp.buyer,
                "barcode": matched_bc
            })
            
    try:
        db.commit()
    except Exception as ex:
        db.rollback()
        ensure_barcode_not_unique(db)
        try:
            db.commit()
        except Exception as ex2:
            db.rollback()
            raise HTTPException(500, f"Erreur lors de la synchronisation : {ex2}")
        
    return {
        "success": True,
        "target": target,
        "synced_count": len(synced),
        "synced_items": synced,
        "message": f"Succès : {len(synced)} codes-barres synchronisés vers {target.upper()} !"
    }


# ── Quick Scanner & Edit Terminal ─────────────────────────────────────────────
class ScannerSaveRequest(BaseModel):
    product_id: int
    name_fr: str
    name_ar: Optional[str] = None
    code_article: Optional[str] = None
    barcode: Optional[str] = None
    buyer: str
    buyers: Optional[List[str]] = None
    sell_price: float
    purchase_price: Optional[float] = None
    category: Optional[str] = None
    fast_panel: Optional[bool] = False
    global_stock_quantity: Optional[int] = None
    seller_stock_quantity: Optional[int] = None
    seller_username: Optional[str] = None

@router.get("/scanner/lookup")
def scanner_lookup(q: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    search_q = (q or "").strip()
    if not search_q:
        raise HTTPException(400, "Veuillez scanner ou saisir un code")
    
    # 1. Match barcode
    prod = db.query(Product).options(joinedload(Product.global_stock)).filter(
        (Product.barcode == search_q) |
        (Product.barcode.like(f"%{search_q}%"))
    ).first()
    
    # 2. Match code_article
    if not prod:
        prod = db.query(Product).options(joinedload(Product.global_stock)).filter(
            func.lower(Product.code_article) == search_q.lower()
        ).first()

    # 3. Match name_fr
    if not prod:
        prod = db.query(Product).options(joinedload(Product.global_stock)).filter(
            Product.name_fr.ilike(f"%{search_q}%")
        ).first()

    if not prod:
        raise HTTPException(404, f"Aucun produit trouvé pour '{search_q}'")

    seller_stocks = db.query(SellerStock).options(joinedload(SellerStock.seller)).filter(
        SellerStock.product_id == prod.id
    ).all()
    
    sellers_info = [
        {"seller_id": ss.seller_id, "username": ss.seller.username, "quantity": ss.quantity}
        for ss in seller_stocks if ss.seller
    ]

    b_low = (prod.buyer or "bilel").lower()
    default_sqty = 0
    default_seller_name = "bilel"
    if "houari" in b_low:
        default_seller_name = "houarii"
    elif "abd" in b_low:
        default_seller_name = "abderahman"
    else:
        default_seller_name = "bilel"

    for ss in sellers_info:
        if ss["username"].lower() == default_seller_name.lower():
            default_sqty = ss["quantity"]
            break

    # Detect all buyers who hold this product (by stock or matching product in DB)
    matching_buyers = set()
    b_curr = (prod.buyer or "Bilel").strip()
    b_curr_low = b_curr.lower()
    if "bil" in b_curr_low:
        matching_buyers.add("Bilel")
    elif "abd" in b_curr_low or "rahman" in b_curr_low:
        matching_buyers.add("Abdrahman")
    elif "houari" in b_curr_low:
        matching_buyers.add("Houari")
    else:
        matching_buyers.add(b_curr)

    # Check seller stocks with quantity > 0
    for ss in sellers_info:
        uname = ss["username"].lower()
        if ss["quantity"] > 0:
            if "bil" in uname:
                matching_buyers.add("Bilel")
            elif "abd" in uname or "rahman" in uname:
                matching_buyers.add("Abdrahman")
            elif "hou" in uname:
                matching_buyers.add("Houari")

    # Also search DB for products with same barcode under other buyers
    clean_bc = (prod.barcode or "").strip()
    if clean_bc:
        other_bcs = db.query(Product).filter(
            (Product.barcode == clean_bc) | (Product.barcode.like(f"%{clean_bc}%")),
            Product.id != prod.id
        ).all()
        for op in other_bcs:
            op_b = (op.buyer or "").lower()
            if "bil" in op_b:
                matching_buyers.add("Bilel")
            elif "abd" in op_b or "rahman" in op_b:
                matching_buyers.add("Abdrahman")
            elif "houari" in op_b:
                matching_buyers.add("Houari")

    # Also check if same product name exists under other buyers
    if prod.name_fr:
        same_name_prods = db.query(Product).filter(
            func.lower(Product.name_fr) == prod.name_fr.lower(),
            Product.id != prod.id
        ).all()
        for op in same_name_prods:
            op_b = (op.buyer or "").lower()
            if "bil" in op_b:
                matching_buyers.add("Bilel")
            elif "abd" in op_b or "rahman" in op_b:
                matching_buyers.add("Abdrahman")
            elif "houari" in op_b:
                matching_buyers.add("Houari")

    exists_both = ("Bilel" in matching_buyers and "Abdrahman" in matching_buyers)

    return {
        "id": prod.id,
        "name_fr": prod.name_fr,
        "name_ar": prod.name_ar or "",
        "code_article": prod.code_article or "",
        "barcode": prod.barcode or "",
        "barcodes": prod.barcode_list,
        "category": prod.category or "Général",
        "purchase_price": prod.purchase_price or 0.0,
        "sell_price": prod.sell_price or 0.0,
        "buyer": prod.buyer or "Bilel",
        "fast_panel": bool(prod.fast_panel),
        "global_stock_quantity": prod.global_stock.quantity if prod.global_stock else 0,
        "seller_stock_quantity": default_sqty,
        "default_seller_username": default_seller_name,
        "seller_stocks": sellers_info,
        "total_stock": (prod.global_stock.quantity if prod.global_stock else 0) + sum(s["quantity"] for s in sellers_info),
        "auto_selected_buyers": list(matching_buyers),
        "exists_in_both_bilel_and_abdrahman": exists_both,
    }

@router.post("/scanner/save")
async def scanner_save_product(data: ScannerSaveRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    prod = db.query(Product).options(joinedload(Product.global_stock)).filter(Product.id == data.product_id).first()
    if not prod:
        raise HTTPException(404, "Produit introuvable")

    prod.name_fr = data.name_fr.strip()
    if data.name_ar is not None:
        prod.name_ar = data.name_ar.strip() or None
    if data.code_article:
        prod.code_article = data.code_article.strip()
    if data.barcode is not None:
        prod.barcode = normalize_barcodes(data.barcode)
    if data.buyer:
        prod.buyer = data.buyer.strip()
    if data.purchase_price is not None:
        prod.purchase_price = round(data.purchase_price, 2)
    prod.sell_price = clamp_margin_sell_price(prod.purchase_price, data.sell_price)
    if data.category:
        prod.category = data.category.strip()
    if data.fast_panel is not None:
        prod.fast_panel = bool(data.fast_panel)

    if data.global_stock_quantity is not None:
        if prod.global_stock:
            prod.global_stock.quantity = max(0, data.global_stock_quantity)
        else:
            gs = GlobalStock(product_id=prod.id, quantity=max(0, data.global_stock_quantity))
            db.add(gs)

    if data.seller_stock_quantity is not None:
        target_uname = data.seller_username
        if not target_uname:
            b_low = (prod.buyer or "bilel").lower()
            target_uname = "houarii" if "houari" in b_low else ("abderahman" if "abd" in b_low else "bilel")
        
        seller_user = db.query(User).filter(func.lower(User.username) == target_uname.lower()).first()
        if seller_user:
            ss = db.query(SellerStock).filter(
                SellerStock.seller_id == seller_user.id,
                SellerStock.product_id == prod.id
            ).first()
            if ss:
                ss.quantity = max(0, data.seller_stock_quantity)
            else:
                ss = SellerStock(
                    seller_id=seller_user.id,
                    product_id=prod.id,
                    quantity=max(0, data.seller_stock_quantity)
                )
                db.add(ss)

    try:
        db.commit()
        db.refresh(prod)
    except Exception as ex:
        db.rollback()
        ensure_barcode_not_unique(db)
        try:
            db.commit()
            db.refresh(prod)
        except Exception as ex2:
            db.rollback()
            raise HTTPException(400, f"Erreur lors de la sauvegarde : {str(ex2)}")
    # Propagate to other buyers if specified
    if data.buyers and isinstance(data.buyers, list):
        for b in data.buyers:
            b_clean = str(b).strip()
            if not b_clean or (prod.buyer and b_clean.lower() == prod.buyer.lower()):
                continue
            
            b_prefix = b_clean[:3]
            target_prod = None
            if prod.barcode:
                target_prod = db.query(Product).filter(
                    Product.buyer.ilike(f"{b_prefix}%"),
                    (Product.barcode == prod.barcode) | (Product.barcode.like(f"%{prod.barcode}%"))
                ).first()
            if not target_prod and prod.name_fr:
                target_prod = db.query(Product).filter(
                    Product.buyer.ilike(f"{b_prefix}%"),
                    func.lower(Product.name_fr) == prod.name_fr.lower()
                ).first()
            
            if target_prod:
                target_prod.sell_price = prod.sell_price
                if prod.purchase_price is not None:
                    target_prod.purchase_price = prod.purchase_price
                if prod.category:
                    target_prod.category = prod.category
                if prod.barcode:
                    target_prod.barcode = prod.barcode
                if prod.fast_panel is not None:
                    target_prod.fast_panel = prod.fast_panel
                db.commit()
                try:
                    await manager.broadcast_all("product.updated", {"id": target_prod.id, "buyer": target_prod.buyer})
                except Exception:
                    pass
            else:
                new_code = gen_code()
                while db.query(Product).filter(Product.code_article == new_code).first():
                    new_code = gen_code()
                new_p = Product(
                    code_article=new_code,
                    barcode=prod.barcode,
                    name_fr=prod.name_fr,
                    name_ar=prod.name_ar,
                    category=prod.category,
                    purchase_price=prod.purchase_price,
                    sell_price=prod.sell_price,
                    min_quantity=prod.min_quantity,
                    description=prod.description,
                    buyer=b_clean,
                    fast_panel=prod.fast_panel
                )
                db.add(new_p)
                db.flush()
                db.add(GlobalStock(product_id=new_p.id, quantity=0))
                try:
                    db.commit()
                    try:
                        await manager.broadcast_all("product.updated", {"id": new_p.id, "buyer": new_p.buyer})
                    except Exception:
                        pass
                except Exception:
                    db.rollback()

    try:
        await manager.broadcast_all("product.updated", {"id": prod.id, "buyer": prod.buyer})
    except Exception:
        pass
    return {
        "status": "success",
        "message": f"Produit '{prod.name_fr}' mis à jour avec succès !",
        "product": {
            "id": prod.id,
            "name_fr": prod.name_fr,
            "code_article": prod.code_article,
            "barcode": prod.barcode,
            "buyer": prod.buyer,
            "sell_price": prod.sell_price,
            "purchase_price": prod.purchase_price,
            "global_stock_quantity": prod.global_stock.quantity if prod.global_stock else 0,
            "fast_panel": prod.fast_panel
        }
    }
