from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User
from passlib.context import CryptContext
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

# Load .env variables
load_dotenv()

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# JWT settings
SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret")
ALGORITHM = "HS256"

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dependency: get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



        from fastapi import Request

# Modified get_current_user that reads token from cookie
# def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
#     token = request.cookies.get("access_token")
#     if not token:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Not authenticated"
#         )


from fastapi.responses import RedirectResponse

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        if request.headers.get("accept", "").startswith("text/html"):
            # 👇 Redirect browser users to landing
            raise RedirectResponse(url="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# Optional version that returns None instead of error
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


# Authenticate user from JWT token in either header or cookie
# def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
#     token = None

#     # Try Authorization header
#     auth_header = request.headers.get("Authorization")
#     if auth_header and auth_header.startswith("Bearer "):
#         token = auth_header.split("Bearer ")[1]

#     # Fallback to cookie
#     if not token:
#         token = request.cookies.get("access_token")

#     if not token:
#         raise HTTPException(status_code=401, detail="Not authenticated")

#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         email: str = payload.get("sub")
#         if email is None:
#             raise HTTPException(status_code=401, detail="Invalid token payload")
#     except JWTError:
#         raise HTTPException(status_code=401, detail="Invalid token")

#     user = db.query(User).filter(User.email == email).first()
#     if user is None:
#         raise HTTPException(status_code=401, detail="User not found")

#     return user

# Utility: Hash password
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# Utility: Verify password
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# Utility: Create JWT token
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Utility: Create magic token
def create_magic_token(email: str, expires_minutes: int = 10):
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode = {"sub": email, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
