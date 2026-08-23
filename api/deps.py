import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from db.base import get_db
from models.user import User, UserRole

SECRET_KEY = os.environ.get("SECRET_KEY", "edushop-secret-2024-very-long-key-do-not-share")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def _get_token(request: Request, token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    # Try cookie first, then Authorization header
    cookie_token = request.cookies.get("edushop_token")
    return cookie_token or token

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme)
) -> User:
    cookie_token = request.cookies.get("edushop_token")
    actual_token = cookie_token or token
    credentials_exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not actual_token:
        raise credentials_exc
    try:
        payload = jwt.decode(actual_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise credentials_exc
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def require_seller(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.seller:
        raise HTTPException(status_code=403, detail="Seller access required")
    return current_user

def get_current_user_any(current_user: User = Depends(get_current_user)) -> User:
    return current_user
