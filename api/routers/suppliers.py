from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.base import get_db
from models.supplier import Supplier, PurchaseInvoice
from models.user import User
from api.deps import require_admin

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

class SupplierCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None

class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None

class InvoiceCreate(BaseModel):
    amount: float
    paid_amount: float = 0.0
    notes: Optional[str] = None

def supplier_dict(s: Supplier) -> dict:
    return {"id": s.id, "name": s.name, "phone": s.phone, "email": s.email, "address": s.address, "debt_balance": s.debt_balance, "created_at": s.created_at}

@router.get("")
def list_suppliers(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return [supplier_dict(s) for s in db.query(Supplier).all()]

@router.post("", status_code=201)
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = Supplier(**data.dict())
    db.add(s); db.commit(); db.refresh(s)
    return supplier_dict(s)

@router.put("/{supplier_id}")
def update_supplier(supplier_id: int, data: SupplierUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s: raise HTTPException(404, "Fournisseur introuvable")
    for field, val in data.dict(exclude_none=True).items():
        setattr(s, field, val)
    db.commit()
    return supplier_dict(s)

@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s: raise HTTPException(404, "Fournisseur introuvable")
    db.delete(s); db.commit()

@router.post("/{supplier_id}/invoice", status_code=201)
def add_invoice(supplier_id: int, data: InvoiceCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s: raise HTTPException(404, "Fournisseur introuvable")
    inv = PurchaseInvoice(supplier_id=supplier_id, amount=data.amount, paid_amount=data.paid_amount, notes=data.notes)
    s.debt_balance += max(0, data.amount - data.paid_amount)
    db.add(inv); db.commit(); db.refresh(inv)
    return {"id": inv.id, "amount": inv.amount, "paid_amount": inv.paid_amount, "notes": inv.notes, "date": inv.date, "supplier_id": inv.supplier_id}

@router.get("/{supplier_id}/invoices")
def list_invoices(supplier_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s: raise HTTPException(404, "Fournisseur introuvable")
    return [{"id": i.id, "amount": i.amount, "paid_amount": i.paid_amount, "notes": i.notes, "date": i.date} for i in s.invoices]
