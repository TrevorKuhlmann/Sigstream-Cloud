import os
import time
import csv
import logging
from datetime import datetime, timedelta
from io import StringIO
from contextlib import asynccontextmanager
from jose import jwt, JWTError
from dotenv import load_dotenv
from fastapi import (
    FastAPI, HTTPException, Request, Depends, status,
    Body, Form, BackgroundTasks, Header
)
from fastapi.responses import (
    HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from auth import (
    create_access_token, get_db, create_magic_token,
    get_current_user, hash_password, verify_password
)
from paddle_webhook import router as paddle_router
from models import DeviceDataIn, DeviceData, DeviceStatus, User
from database import SessionLocal
from schemas import UserCreate, Token
from email_utils import send_magic_link_email
from crud import insert_data, update_heartbeat

from authlib.integrations.starlette_client import OAuth, OAuthError

# ----------------------------- Load Env -----------------------------
load_dotenv()
API_KEY = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")
SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret")
ALGORITHM = "HS256"
PADDLE_ENV = os.getenv("PADDLE_ENV", "sandbox")
PADDLE_CLIENT_TOKEN = os.getenv("PADDLE_CLIENT_TOKEN")

# ----------------------------- OAuth Setup -----------------------------
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ----------------------------- App & Middleware -----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Install session middleware **here**, not inside any function
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,    # must match your JWT secret
    session_cookie="session",
    https_only=True,          # set False for local testing over HTTP
    max_age=3600,
    same_site="lax"
)

templates = Jinja2Templates(directory="templates")
templates.env.filters['format_ts'] = lambda ts: datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
logging.basicConfig(level=logging.INFO)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# ----------------------------- Dependency -----------------------------
def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    try:
        return get_current_user(request, db)
    except Exception:
        return None

# ----------------------------- Authentication & Subscription -----------------------------

@app.get("/post-purchase", response_class=HTMLResponse)
async def post_purchase(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("post_purchase.html", {"request": request, "user": user})

@app.get("/login-redirect", response_class=RedirectResponse)
async def login_redirect(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result = db.execute(text("SELECT has_active_subscription(:email)"), {"email": user.email}).scalar()
    if result == 'ACTIVE':
        return RedirectResponse("/summary", status_code=302)
    return RedirectResponse("/", status_code=302)

@app.get("/check-subscription")
async def check_subscription(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(text("SELECT has_active_subscription(:email)"), {"email": user.email}).scalar()
    return {"active": result == 'ACTIVE'}

@app.post("/magic-login-register", response_class=HTMLResponse)
async def magic_login_register(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if user:
        return templates.TemplateResponse("magic_login.html", {
            "request": request,
            "error": "You're already registered. Please sign in instead."
        })
    user = User(email=email, hashed_password="", customer_name="New User")
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(data={"sub": email}, expires_delta=timedelta(minutes=10))
    magic_link = f"{request.base_url}magic-auth?token={token}"
    background_tasks.add_task(send_magic_link_email, email, magic_link)
    return templates.TemplateResponse("check_email.html", {
        "request": request,
        "email": email,
        "message": "Check your inbox and click the magic link to log in."
    })

@app.post("/magic-login-signin", response_class=HTMLResponse)
async def magic_signin(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return templates.TemplateResponse("magic_login_form.html", {
            "request": request,
            "error": "No account found with this email. Please sign up first.",
            "suggestion": "Go to Sign Up",
            "signup_link": "/register-form"
        })
    token = create_magic_token(email)
    magic_link = str(request.url_for("complete_magic_login")) + f"?token={token}"
    background_tasks.add_task(send_magic_link_email, to_email=email, link_url=magic_link)
    return templates.TemplateResponse("check_email.html", {
        "request": request,
        "email": email,
        "message": "Check your email and click the magic link to sign in."
    })

@app.get("/magic-auth", response_class=HTMLResponse)
def complete_magic_login(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
    except jwt.ExpiredSignatureError:
        return templates.TemplateResponse("expired_token.html", {
            "request": request,
            "error": "Your magic link has expired. Please try logging in again."
        })
    except jwt.JWTError:
        return templates.TemplateResponse("expired_token.html", {
            "request": request,
            "error": "Invalid token. Please try again."
        })
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    access_token = create_access_token(data={"sub": user.email})
    response = templates.TemplateResponse("magic_redirect.html", {
        "request": request, "message": "Logging you in..."
    })
    response.set_cookie("access_token", access_token, httponly=True)
    return response

# ----------------------------- Google OAuth Routes -----------------------------
@app.get("/auth/google")
async def auth_google(request: Request):
    redirect_uri = request.url_for("auth_google_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        raise HTTPException(400, "Google OAuth failed")
    user_info = token.get("userinfo") or await oauth.google.parse_id_token(request, token)
    email = user_info["email"]
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, hashed_password="", customer_name=user_info.get("name", ""))
        db.add(user)
        db.commit()
        db.refresh(user)
    access_token = create_access_token(data={"sub": user.email})
    response = RedirectResponse(url="/login-redirect", status_code=302)
    response.set_cookie("access_token", access_token, httponly=True)
    return response

# ----------------------------- Traditional Auth & Core API -----------------------------
@app.get("/register-form", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register-form")
def register_form_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    customer_name: str = Form(...),
    db: Session = Depends(get_db)
):
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Email already registered"
        })
    new_user = User(email=email, hashed_password=hash_password(password), customer_name=customer_name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return RedirectResponse(url="/login-form", status_code=302)

@app.get("/login-form", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("magic_login_form.html", {"request": request})

@app.post("/login-form")
def login_form_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("magic_login_form.html", {
            "request": request, "error": "Invalid credentials"
        })
    token = create_access_token(data={"sub": user.email})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True)
    return response

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(email=user.email, hashed_password=hash_password(user.password),
                    customer_name=user.customer_name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered successfully", "user_id": new_user.id}

@app.post("/token", response_model=Token)
def login_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(data={"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

# ----------------------------- Data & Dashboard -----------------------------
@app.post("/data")
def receive_data(payload: DeviceDataIn, db: Session = Depends(get_db), x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    ts = payload.timestamp or int(time.time())
    insert_data(payload.device_id, payload.data, ts, db)
    update_heartbeat(payload.device_id, ts, db)
    return {"status": "success"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    statuses = db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "statuses": statuses, "now": int(time.time()), "user": current_user
    })

@app.get("/summary", response_class=HTMLResponse)
def summary(request: Request, device_id: str = None, db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    query = db.query(DeviceData).join(DeviceStatus, DeviceData.device_id == DeviceStatus.device_id)\
             .filter(DeviceStatus.user_id == current_user.id)
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()
    return templates.TemplateResponse("summary.html", {
        "request": request, "records": records, "filter_id": device_id
    })

# ... (rest of your routes for export, devices, legal pages, landing, logout, and paddle webhooks)


@app.get("/export")
def export_csv(device_id: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    device_ids = [d.device_id for d in db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id)]
    query = db.query(DeviceData).filter(DeviceData.device_id.in_(device_ids))
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).all()

    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(["ID", "Device ID", "Data", "Timestamp"])
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for row in records:
            writer.writerow([row.id, row.device_id, row.data, row.timestamp])
            yield data.getvalue(); data.seek(0); data.truncate(0)

    return StreamingResponse(generate(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=sigstream_export.csv"
    })

# ----------------------------- Devices -----------------------------



from fastapi import Header

@app.post("/device-data")
def device_data(
    payload: DeviceDataIn,
    db: Session = Depends(get_db),
    api_key: str = Header(None)
):
    expected_key = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Optional: check if device is registered, save data
    ts = payload.timestamp or int(time.time())
    insert_data(payload.device_id, payload.data, ts, db, None)
    update_heartbeat(payload.device_id, ts, db, None)
    return {"status": "success"}


@app.get("/devices", response_class=HTMLResponse)
def device_management(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    devices = db.query(DeviceStatus).filter(DeviceStatus.user_id == user.id).all()
    return templates.TemplateResponse("devices.html", {"request": request, "devices": devices, "user": user})

@app.post("/devices/claim")
def claim_device_form(device_id: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    device = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id).first()
    if not device or device.user_id:
        raise HTTPException(status_code=404, detail="Device not found or already claimed")
    device.user_id = user.id
    db.commit()
    return RedirectResponse(url="/devices", status_code=302)

@app.post("/devices/unclaim")
def unclaim_device(device_id: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    device = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id, DeviceStatus.user_id == user.id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or not owned by you")
    device.user_id = None
    db.commit()
    return RedirectResponse(url="/devices", status_code=302)

@app.post("/devices/label")
def update_device_label(device_id: str = Form(...), new_label: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    device = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id, DeviceStatus.user_id == user.id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or not owned by you")
    device.label = new_label
    db.commit()
    return RedirectResponse(url="/devices", status_code=302)

# ----------------------------- Legal Pages -----------------------------

@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})

@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

@app.get("/refund", response_class=HTMLResponse)
def refund(request: Request):
    return templates.TemplateResponse("refund.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def landing_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    # 1. Determine subscription status
    subscription_status = None
    if current_user:
        result = db.execute(text("SELECT has_active_subscription(:email)"), {"email": current_user.email}).scalar()
        subscription_status = result.lower() if result else None

        # 2. If subscribed, redirect immediately (and disable caching)
        if subscription_status in ("active", "trialing"):
            response = RedirectResponse("/summary", status_code=302)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            return response

    # 3. Otherwise render landing page, also with no-store so back always revalidates
    response = templates.TemplateResponse("landing.html", {
        "request": request,
        "user_email": current_user.email if current_user else None,
        "user_subscription_status": subscription_status,
        "paddle_token": PADDLE_CLIENT_TOKEN
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token")
    return response



app.include_router(paddle_router)
