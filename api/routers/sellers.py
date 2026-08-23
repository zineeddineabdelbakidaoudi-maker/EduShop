from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from passlib.context import CryptContext
from db.base import get_db
from models.user import User, UserRole
from models.sale import Sale
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

def seller_stats(user: User, db: Session) -> dict:
    sales = db.query(Sale).filter(Sale.seller_id == user.id, Sale.is_return == False).all()
    returns = db.query(Sale).filter(Sale.seller_id == user.id, Sale.is_return == True).count()
    revenue = sum(s.total for s in sales)
    profit = sum(
        sum((si.unit_price - si.purchase_price) * si.quantity for si in s.items)
        for s in sales
    )
    return {
        "id": user.id, "username": user.username, "role": user.role,
        "created_at": user.created_at,
        "total_sales": len(sales), "total_revenue": revenue,
        "total_profit": profit, "total_returns": returns,
    }

@router.get("")
def list_sellers(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sellers = db.query(User).filter(User.role == UserRole.seller).all()
    return [seller_stats(s, db) for s in sellers]

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
    db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}

@router.delete("/{seller_id}", status_code=204)
def delete_seller(seller_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == seller_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    db.delete(user)
    db.commit()
