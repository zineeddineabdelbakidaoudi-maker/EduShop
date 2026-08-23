from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from pydantic import BaseModel
from db.base import get_db
from models.user import User, UserRole
from api.deps import create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

class LoginRequest(BaseModel):
    username: str
    pin: str

@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not pwd_ctx.verify(req.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="Identifiant ou PIN incorrect")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    response.set_cookie("edushop_token", token, httponly=True, samesite="lax", max_age=86400)
    return {"access_token": token, "token_type": "bearer", "role": user.role, "username": user.username, "id": user.id}

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("edushop_token")
    return {"detail": "Logged out"}

class ChangePasswordRequest(BaseModel):
    old_pin: str
    new_pin: str

@router.post("/change-password")
def change_password(req: ChangePasswordRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not pwd_ctx.verify(req.old_pin, current_user.pin_hash):
        raise HTTPException(status_code=400, detail="L'ancien mot de passe / PIN est incorrect.")
    if len(req.new_pin) < 4:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit comporter au moins 4 caractères.")
    
    current_user.pin_hash = pwd_ctx.hash(req.new_pin)
    db.commit()
    return {"detail": "Mot de passe modifié avec succès !"}

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "role": current_user.role, "created_at": current_user.created_at}
