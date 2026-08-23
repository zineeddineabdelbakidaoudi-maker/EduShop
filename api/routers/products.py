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

@router.post("/import-image")
async def import_from_image(file: UploadFile = File(...), admin: User = Depends(require_admin)):
    """OCR: Detect product names and prices from an invoice photo with robust error handling."""
    contents = await file.read()
    text = ""
    ocr_available = False
    
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(io.BytesIO(contents)).convert("L")
        text = pytesseract.image_to_string(img, lang="fra+ara", config="--psm 6")
        ocr_available = True
    except Exception as e:
        # Tesseract not installed locally on Windows or missing PATH
        ocr_available = False
        text = ""
    
    products_detected = []
    if ocr_available and text:
        skip_kw = [
            "FOURNITURES", "GENERALES", "CENTRE", "SARL", "RUE", "RC", "NIF", "TEL", "CLIENT", 
            "FACTURE", "DATE", "TOTAL HT", "TVA", "TOTAL TTC", "MERCI", "PAGE", "BON DE", "REGLEMENT",
            "CODE CODE-BARRES", "DESIGNATION", "CATEGORIE", "P.ACHAT", "QTE", "P.VENTE"
        ]
        categories_known = ["Papeterie", "Accessoires", "Cahiers", "Classeurs", "Sacs & Cartables", "Fournitures", "Bureau", "Livres", "Manuels", "Général"]

        for line in [l.strip() for l in text.split("\n") if l.strip()]:
            if len(line) < 4:
                continue
            if any(kw in line.upper() for kw in skip_kw):
                continue
            
            clean_line = re.sub(r'\b(DA|DZD|€)\b', '', line, flags=re.IGNORECASE).strip()
            
            # 1. Code
            code = ""
            code_m = re.match(r'^(ART[-\s]?\d+|[A-Z]{2,4}[-\s]?\d+)\b', clean_line, re.IGNORECASE)
            if code_m:
                code = code_m.group(1).replace(" ", "-").upper()
                clean_line = clean_line[len(code_m.group(0)):].strip()
            
            # 2. Barcode
            barcode = ""
            bc_m = re.match(r'^(\d{8,14})\b', clean_line)
            if bc_m:
                barcode = bc_m.group(1)
                clean_line = clean_line[len(bc_m.group(0)):].strip()
            
            # 3. Numbers at end: [PA] [Qty] [PV] or [PA] [Qty]
            num_m = re.search(r'(\d+[\.,]?\d*)\s+(\d+)(?:\s+(\d+[\.,]?\d*))?$', clean_line)
            pa, qty, pv = 0.0, 10, 0.0
            if num_m:
                pa = float(num_m.group(1).replace(',', '.'))
                qty = int(num_m.group(2))
                pv = float(num_m.group(3).replace(',', '.')) if num_m.group(3) else round(pa * 1.25, 2)
                clean_line = clean_line[:num_m.start()].strip()
            
            # 4. Category & Designation
            category = "Papeterie"
            for cat in categories_known:
                if re.search(rf'\b{re.escape(cat)}\b', clean_line, re.IGNORECASE):
                    category = cat
                    clean_line = re.sub(rf'\b{re.escape(cat)}\b', '', clean_line, flags=re.IGNORECASE).strip()
                    break
            
            designation = clean_line.strip(" :-|;")
            if not designation and code:
                designation = f"Article {code}"
            
            if designation and (len(designation) >= 2 or pa > 0):
                if not code:
                    code = gen_code()
                if pa > 0 and (pv <= 0 or pv <= pa):
                    pv = round(pa * 1.25, 2)
                
                products_detected.append({
                    "code": code,
                    "barcode": barcode,
                    "name_fr": designation[:120],
                    "category": category,
                    "purchase_price": pa,
                    "quantity": qty,
                    "sell_price": pv
                })
    
    return {
        "ocr_available": ocr_available,
        "products": products_detected[:100],
        "raw_text": text[:2000] if text else "",
        "message": "Facture analysée avec succès" if ocr_available else "Moteur OCR Tesseract côté serveur non disponible."
    }

