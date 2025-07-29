from fastapi import (
    FastAPI, HTTPException, Request, Depends, Form, BackgroundTasks, Header
)
from fastapi.responses import (
    HTMLResponse, StreamingResponse, RedirectResponse
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth, OAuthError
from sqlalchemy.orm import Session
from sqlalchemy import text
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from jose import jwt, JWTError
from dotenv import load_dotenv
from secrets import token_hex
from io import StringIO
import logging
import httpx
import os
import time
import csv

from auth import (
    create_access_token,
    get_db,
    create_magic_token,
    get_current_user_api,
    get_current_user_browser,
    get_current_user_optional,
    hash_password,
    verify_password
)
from models import DeviceDataIn, DeviceData, DeviceStatus, User, ApiKey
from database import SessionLocal
from schemas import UserCreate, Token
from email_utils import send_magic_link_email, send_confirmation_email
from crud import insert_data, update_heartbeat
from paddle_webhook import router as paddle_router
from pydantic import BaseModel

# ----------------------------- Load Environment -----------------------------
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret")
PADDLE_CLIENT_TOKEN = os.getenv("PADDLE_CLIENT_TOKEN")
PADDLE_API_KEY = os.getenv("PADDLE_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# ----------------------------- FastAPI Setup -----------------------------
@asynccontextmanager
def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="session",
    https_only=True,
    max_age=3600,
    same_site="lax",
)
templates = Jinja2Templates(directory="templates")
templates.env.filters['format_ts'] = lambda ts: datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
logging.basicConfig(level=logging.INFO)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ----------------------------- Routes -----------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_browser)
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    statuses = db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id).all()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "statuses": statuses, "now": int(time.time()), "user": current_user}
    )

@app.get("/summary", response_class=HTMLResponse)
async def summary(
    request: Request,
    device_id: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_browser)
):
    if isinstance(current_user, RedirectResponse):
        return current_user

    query = (
        db.query(DeviceData)
          .join(DeviceStatus, DeviceData.device_id == DeviceStatus.device_id)
          .filter(DeviceStatus.user_id == current_user.id)
    )
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()

    sub_id = db.execute(
        text("""
            SELECT b.id
              FROM public.customers a
              JOIN public.subscriptions b ON a.id = b.customer_id
             WHERE b.status = 'active' AND a.email = :email
        """),
        {"email": current_user.email}
    ).scalar()

    cancel_url = update_pm_url = None
    if sub_id:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://sandbox-api.paddle.com/subscriptions/{sub_id}",
                headers={"Authorization": f"Bearer {PADDLE_API_KEY}"}
            )
        payload = resp.json()
        urls = payload.get("data", {}).get("management_urls", {})
        cancel_url = urls.get("cancel")
        update_pm_url = urls.get("update_payment_method")

    return templates.TemplateResponse(
        "summary.html",
        {
            "request": request,
            "records": records,
            "filter_id": device_id,
            "cancel_url": cancel_url,
            "update_pm_url": update_pm_url,
            "user": current_user
        }
    )

@app.get("/api-management", response_class=HTMLResponse)
def api_management(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_browser)
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    api_keys = (
        db.query(ApiKey)
          .filter(ApiKey.user_id == current_user.id)
          .order_by(ApiKey.created_at.desc())
          .all()
    )
    return templates.TemplateResponse(
        "api-management.html",
        {"request": request, "api_keys": api_keys, "user": current_user}
    )

@app.get("/post-purchase", response_class=HTMLResponse)
def post_purchase(
    request: Request,
    user: User = Depends(get_current_user_browser)
):
    if isinstance(user, RedirectResponse):
        return user
    return templates.TemplateResponse(
        "post_purchase.html",
        {"request": request, "user": user}
    )

@app.get("/login-redirect", response_class=RedirectResponse)
def login_redirect(
    request: Request,
    user: User = Depends(get_current_user_browser),
    db: Session = Depends(get_db)
):
    if isinstance(user, RedirectResponse):
        return user
    result = db.execute(
        text("SELECT has_active_subscription(:email)"),
        {"email": user.email}
    ).scalar()
    return RedirectResponse("/summary" if result == 'ACTIVE' else "/")

@app.get("/check-subscription")
def check_subscription(
    user: User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    result = db.execute(
        text("SELECT has_active_subscription(:email)"),
        {"email": user.email}
    ).scalar()
    return {"active": result == 'ACTIVE'}

@app.get("/export")
def export_csv(
    device_id: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_browser)
):
    if isinstance(current_user, RedirectResponse):
        return current_user
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

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sigstream_export.csv"}
    )

# ----------------------------- Include Router -----------------------------
app.include_router(paddle_router)

# ----------------------------- API Key Creation -----------------------------
@app.get("/api-management/create")
def create_api_key(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_browser)
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    new_key = ApiKey(
        user_id=current_user.id,
        key=token_hex(16),
        status="active"
    )
    db.add(new_key)
    db.commit()
    return RedirectResponse("/api-management", status_code=302)

# ----------------------------- API Key Revocation -----------------------------
@app.post("/api-management/revoke/{key_id}")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_browser)
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    api_key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.user_id == current_user.id
    ).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found.")
    api_key.status = "revoked"
    api_key.revoked_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/api-management", status_code=302)
