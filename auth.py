from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from dotenv import load_dotenv
from database import SessionLocal, get_db
from models import User
from datetime import datetime, timedelta
import os

# ----------------------------- Load env & settings -----------------------------
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret")
ALGORITHM = "HS256"

# ----------------------------- Auth Schemes -----------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ----------------------------- DB Dependency -----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------------------- API Client Auth (JSON 401) -----------------------------
def get_current_user_api(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ----------------------------- HTML View Auth (Redirect) -----------------------------
def get_current_user_browser(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            return RedirectResponse(url="/")
    except JWTError:
        return RedirectResponse(url="/")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        return RedirectResponse(url="/")
    return user

# ----------------------------- Optional User (nullable) -----------------------------
async def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
        user = db.query(User).filter(User.email == email).first()
        return user
    except JWTError:
        return None

# ----------------------------- Auth Utilities -----------------------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_magic_token(email: str, expires_minutes: int = 10):
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode = {"sub": email, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
