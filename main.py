import os
import time
import csv
import anyio
from fastapi import status
import os, httpx
from routes_devapi import router as devapi_router
from sse_broker import broker
from secrets import token_hex
from datetime import datetime, timedelta
import logging
from sqlalchemy import func
from sqlalchemy.orm import aliased
from fastapi import Query
from datetime import datetime, timedelta
from io import StringIO
from contextlib import asynccontextmanager
from sqlalchemy import text
from jose import jwt, JWTError
from dotenv import load_dotenv
from sqlalchemy import and_, func, text
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import ApiKey
from auth import get_db

from datetime import datetime
from sqlalchemy import and_, func, text


from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Depends,
    Form,
    BackgroundTasks,
    Header,
)
from fastapi.responses import (
    HTMLResponse,
    StreamingResponse,
    RedirectResponse,
    JSONResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime
from auth import (
    create_access_token,
    get_db,
    create_magic_token,
    get_current_user,
    hash_password,
    verify_password,
)
from paddle_webhook import router as paddle_router
from models import DeviceDataIn, DeviceData, DeviceStatus, User
from database import SessionLocal
from schemas import UserCreate, Token
from email_utils import send_magic_link_email, send_confirmation_email
from crud import insert_data, update_heartbeat

from authlib.integrations.starlette_client import OAuth, OAuthError


from models import ApiKey  # 👈 new model you added to models.py
from pydantic import BaseModel

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from xml.etree import ElementTree as ET
import datetime as dt

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)  # prevent crash if folder not present at deploy


# === Canonical header names for v1 ===
CANON_KEY_HDR = "x-api-key"
CANON_DEV_HDR = "x-device-id"

def read_auth_headers(request: Request) -> tuple[str, str]:
    """
    Read canonical auth headers. Raise 400 if absent.
    """
    api_key = request.headers.get(CANON_KEY_HDR)
    device_id = request.headers.get(CANON_DEV_HDR)
    if not api_key or not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Api-Key or X-Device-Id")
    return api_key, device_id


# ----------------------------- Load Env -----------------------------
load_dotenv()
API_KEY             = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")
SECRET_KEY          = os.getenv("SECRET_KEY", "your_default_secret")
ALGORITHM           = "HS256"
PADDLE_ENV          = os.getenv("PADDLE_ENV", "sandbox")
PADDLE_CLIENT_TOKEN = os.getenv("PADDLE_CLIENT_TOKEN")
PADDLE_API_KEY      = os.getenv("PADDLE_API_KEY")   

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

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,    # must match your JWT secret
    session_cookie="session",
    https_only=True,          # set False for local testing over HTTP
    max_age=3600,
    same_site="lax",
)

# ----------------------------- Routers -----------------------------

app.include_router(devapi_router)

templates = Jinja2Templates(directory="templates")


#--------------------------------------------------------
def format_relative(ts):
    if not ts:
        return {"text": "-", "cls": "text-gray-400"}

    now = datetime.utcnow()
    diff = now - datetime.utcfromtimestamp(ts)

    seconds = int(diff.total_seconds())
    minutes = seconds // 60
    hours   = minutes // 60
    days    = diff.days

    if seconds < 60:
        return {"text": "Just now", "cls": "text-green-600"}
    elif minutes < 10:
        return {"text": f"{minutes} min ago", "cls": "text-green-600"}
    elif minutes < 60:
        return {"text": f"{minutes} min ago", "cls": "text-yellow-500"}
    elif hours < 24:
        return {"text": f"{hours} hours ago", "cls": "text-orange-500"}
    elif days == 1:
        return {"text": "Yesterday", "cls": "text-red-500"}
    else:
        return {"text": f"{days} days ago", "cls": "text-red-600"}

# 🔧 Register the filter for use in Jinja templates
templates.env.filters["relative_ts"] = format_relative

templates.env.filters['format_ts'] = lambda ts: datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
logging.basicConfig(level=logging.INFO)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


# ----------------------------- Dependencies -----------------------------
def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    try:
        return get_current_user(request, db)
    except Exception:
        return None


# ----------------------------- Post-Purchase & Redirect -----------------------------
@app.get("/post-purchase", response_class=HTMLResponse)
async def post_purchase(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("post_purchase.html", {"request": request, "user": user})


@app.get("/login-redirect", response_class=RedirectResponse)
async def login_redirect(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(
        text("SELECT has_active_subscription(:email)"),
        {"email": user.email},
    ).scalar()
    if result == 'ACTIVE':
        response = RedirectResponse("/summary", status_code=302)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response
    return RedirectResponse("/", status_code=302)


@app.get("/check-subscription")
async def check_subscription(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(
        text("SELECT has_active_subscription(:email)"),
        {"email": user.email},
    ).scalar()
    return {"active": result == 'ACTIVE'}

#----------------------------- Admin Purge Old Telemetry -----------------------------

@app.get("/admin/purge-old", include_in_schema=False)
def purge_old_telemetry(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # You can add stricter logic here to restrict who can purge
    delete_old_device_data(db, days=7)
    return {"status": "ok", "message": "Old telemetry data purged."}



# ----------------------------- Magic Link Registration & Sign-In -----------------------------
@app.post("/magic-login-register", response_class=HTMLResponse)
async def magic_login_register(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if user:
        return templates.TemplateResponse("magic_login.html", {
            "request": request,
            "error": "You're already registered. Please sign in instead.",
        })

    # Create unconfirmed user
    user = User(email=email, hashed_password="", customer_name="New User", email_confirmed=False)
    db.add(user)
    db.commit()
    db.refresh(user)

    # Send magic link
    token      = create_access_token(data={"sub": email}, expires_delta=timedelta(minutes=10))
    magic_link = f"{request.base_url}magic-auth?token={token}"
    background_tasks.add_task(send_magic_link_email, email, magic_link)

    return templates.TemplateResponse("check_email.html", {
        "request": request,
        "email": email,
        "message": "Check your inbox and click the magic link to log in.",
    })

#----------------------------- Claim Request Model -----------------------------

class ClaimRequest(BaseModel):
    api_key: str
    machine_id: str
    description: str  # 👈 Add this

#------------------------- Magic Link Sign-In -----------------------------
@app.post("/magic-login-signin", response_class=HTMLResponse)
async def magic_signin(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return templates.TemplateResponse("magic_login_form.html", {
            "request": request,
            "error": "No account found with this email. Please sign up first.",
            "suggestion": "Go to Sign Up",
            "signup_link": "/register-form",
        })

    token      = create_magic_token(email)
    magic_link = f"{request.url_for('complete_magic_login')}?token={token}"
    background_tasks.add_task(send_magic_link_email, email, magic_link)

    return templates.TemplateResponse("check_email.html", {
        "request": request,
        "email": email,
        "message": "Check your email and click the magic link to sign in.",
    })

#----------------------------- Developer API Documentation -----------------------------
@app.get("/developer-api", response_class=HTMLResponse)
def developer_api_page(request: Request):
    return templates.TemplateResponse("developer_api.html", {"request": request})

#----------------------------- Magic Link Completion -----------------------------
@app.get("/magic-auth", response_class=HTMLResponse)
async def complete_magic_login(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Decode & validate
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email   = payload.get("sub")
        if not email:
            raise JWTError()
    except JWTError:
        return templates.TemplateResponse("expired_token.html", {
            "request": request,
            "error": "Invalid or expired magic link. Please try again."
        })

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # If not yet confirmed, send confirmation
    if not user.email_confirmed:
        send_confirmation_email(
            background_tasks,
            to_email=user.email,
            base_url=str(request.base_url),
        )
        return templates.TemplateResponse("please_confirm.html", {
            "request": request,
            "email": user.email,
        })

    # Otherwise issue JWT and redirect
    access_token = create_access_token(data={"sub": user.email})
    response = templates.TemplateResponse("magic_redirect.html", {
        "request": request,
        "message": "Logging you in..."
    })
    response.set_cookie("access_token", access_token, httponly=True)
    return response


# ----------------------------- Email Confirmation -----------------------------
@app.get("/confirm-email", response_class=HTMLResponse)
def confirm_email(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "email_confirm":
            raise JWTError()
        email = payload["sub"]
    except JWTError:
        return templates.TemplateResponse("confirm_email.html", {
            "request": request,
            "error": "Invalid or expired confirmation link."
        })

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.email_confirmed:
        user.email_confirmed    = True
        user.email_confirmed_at = datetime.utcnow()
        db.commit()

    return templates.TemplateResponse("confirm_email.html", {
        "request": request,
        "success": "Your email has been confirmed! You can now log in."
    })


# ----------------------------- Google OAuth -----------------------------
@app.get("/auth/google")
async def auth_google(request: Request):
    redirect_uri = request.url_for("auth_google_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@app.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        token     = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo") or await oauth.google.parse_id_token(request, token)
        email     = user_info["email"]
    except OAuthError:
        raise HTTPException(400, "Google OAuth failed")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            hashed_password="",
            customer_name=user_info.get("name", ""),
            email_confirmed=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.email_confirmed:
        send_confirmation_email(
            background_tasks,
            to_email=user.email,
            base_url=str(request.base_url),
        )
        return templates.TemplateResponse("please_confirm.html", {
            "request": request,
            "email": user.email,
        })

    access_token = create_access_token(data={"sub": user.email})
    response = RedirectResponse(url="/login-redirect", status_code=302)
    response.set_cookie("access_token", access_token, httponly=True)
    return response


# ----------------------------- Traditional Auth & Core API -----------------------------
@app.get("/register-form", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register-form", response_class=HTMLResponse)
async def register_form_post(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    customer_name: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email already registered"
        })

    new_user = User(
        email=email,
        hashed_password=hash_password(password),
        customer_name=customer_name,
        email_confirmed=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    send_confirmation_email(
        background_tasks,
        to_email=new_user.email,
        base_url=str(request.base_url),
    )

    return templates.TemplateResponse("please_confirm.html", {
        "request": request,
        "email": new_user.email
    })


@app.get("/login-form", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("magic_login_form.html", {"request": request})


@app.post("/login-form", response_class=HTMLResponse)
async def login_form_post(
    request: Request,
    background_tasks: BackgroundTasks,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("magic_login_form.html", {
            "request": request,
            "error": "Invalid credentials"
        })

    if not user.email_confirmed:
        send_confirmation_email(
            background_tasks,
            to_email=user.email,
            base_url=str(request.base_url),
        )
        return templates.TemplateResponse("please_confirm.html", {
            "request": request,
            "email": user.email
        })

    token = create_access_token(data={"sub": user.email})
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie("access_token", token, httponly=True)
    return resp


@app.post("/register")
def register_api(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(
        email=user.email,
        hashed_password=hash_password(user.password),
        customer_name=user.customer_name
    )
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


#----------------------------- API Key Validation -----------------------------

def validate_device_key(api_key_str: str, machine_id: str, db: Session):
    if not api_key_str or not machine_id:
        raise HTTPException(status_code=400, detail="Missing API key or device ID.")
    api_key = db.query(ApiKey).filter(
        ApiKey.key == api_key_str,
        ApiKey.status == "active"
    ).first()
    if not api_key:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    if api_key.device_id != machine_id:
        raise HTTPException(status_code=403, detail=f"Key mismatch: bound to {api_key.device_id}.")
    return api_key


# ----------------------------- Data Endpoints -----------------------------
# @app.post("/data")
# def receive_data(
#     payload: DeviceDataIn,
#     db: Session = Depends(get_db),
#     x_api_key: str = Header(None),
#     x_device_id: str = Header(None),
# ):
#     logging.info(f"Received /data call. API key: {x_api_key[:6]}..., Device ID header: {x_device_id}")
#     logging.info(f"Payload: {payload.json()}")

#     try:
#         api_key = validate_device_key(x_api_key, x_device_id, db)
#         user = api_key.user
#         ts = payload.timestamp or int(time.time())

#         logging.info(f"Validated API key. Inserting data: {payload.data}")
#         insert_data(payload.device_id, payload.data, ts, db, user)

#         logging.info("Calling update_heartbeat...")
#         update_heartbeat(payload.device_id, ts, db, user)


#         # --- NEW: fire-and-forget SSE publish (non-blocking, best-effort) ---
#         try:
#             import asyncio
#             # optional label for nicer client display
#             device_label = db.query(DeviceStatus.label)\
#                 .filter(DeviceStatus.user_id == user.id, DeviceStatus.device_id == payload.device_id)\
#                 .scalar()

#             live_payload = {
#                 "device_id": payload.device_id,
#                 "label": device_label,
#                 "data": payload.data,
#                 "timestamp": ts,
#                 "ts_iso": datetime.utcfromtimestamp(ts).isoformat() + "Z",
#             }
#             asyncio.create_task(
#                 broker.publish((int(user.id), str(payload.device_id)), live_payload, event="telemetry")
#             )
#         except Exception:
#             logging.exception("SSE publish failed (non-fatal)")
#         # --- END NEW ---

#         return {"status": "success"}
#     except Exception as e:
#         logging.exception("Error in /data endpoint")
#         raise


# ----------------------------- Data Endpoint (canonical) -----------------------------
@app.post("/data")
def receive_data(
    payload: DeviceDataIn,              # { device_id, data, timestamp? }
    request: Request,
    db: Session = Depends(get_db),
):
    # headers are canonical
    api_key_str, device_id_hdr = read_auth_headers(request)

    # enforce header/body consistency
    if device_id_hdr != payload.device_id:
        raise HTTPException(status_code=400, detail="device_id mismatch between header and body")

    # 403 if revoked/invalid or bound to different device
    api_key = validate_device_key(api_key_str, device_id_hdr, db)
    user = api_key.user

    ts = payload.timestamp or int(time.time())

    insert_data(payload.device_id, payload.data, ts, db, user)
    update_heartbeat(payload.device_id, ts, db, user)

    # --- SSE publish (unchanged) ---
    try:
        import anyio
        device_label = db.query(DeviceStatus.label)\
            .filter(DeviceStatus.user_id == user.id,
                    DeviceStatus.device_id == payload.device_id)\
            .scalar()

        telemetry_payload = {
            "device_id": payload.device_id,
            "label": device_label,
            "data": payload.data,
            "timestamp": ts,
            "ts_iso": datetime.utcfromtimestamp(ts).isoformat() + "Z",
        }
        heartbeat_payload = {
            "device_id": payload.device_id,
            "timestamp": ts,
            "ts_iso": datetime.utcfromtimestamp(ts).isoformat() + "Z",
            "status": "online"
        }

        anyio.from_thread.run(broker.publish, (int(user.id), str(payload.device_id)), telemetry_payload, "telemetry")
        anyio.from_thread.run(broker.publish, (int(user.id), str(payload.device_id)), heartbeat_payload, "heartbeat")
    except Exception:
        logging.exception("SSE publish failed (non-fatal)")
    # --- end SSE ---

    return {"status": "success"}




# ----------------------------- Heartbeat Endpoint -----------------------------
# ----------------------------- Heartbeat Endpoint (canonical) -----------------------------
class HeartbeatPayload(BaseModel):
    device_id: str
    heartbeat_time: str
    status: str

@app.post("/api/heartbeat")
def receive_heartbeat(
    payload: HeartbeatPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    # headers are the single source of truth
    api_key_str, device_id_hdr = read_auth_headers(request)

    # enforce header/body consistency
    if device_id_hdr != payload.device_id:
        raise HTTPException(status_code=400, detail="device_id mismatch between header and body")

    # 403 if revoked/invalid or bound to different device
    api_key = validate_device_key(api_key_str, device_id_hdr, db)

    ts = int(datetime.fromisoformat(payload.heartbeat_time).timestamp())
    update_heartbeat(payload.device_id, ts, db, api_key.user)
    return {"status": "heartbeat received"}



# ----------------------------- Status Check Endpoint -----------------------------
@app.post("/api/status")
def api_status(  # <— rename from `status` to `api_status`
    request: Request,
    db: Session = Depends(get_db)
):
    api_key_str, device_id = read_auth_headers(request)

    rec = db.query(ApiKey).filter(ApiKey.key == api_key_str).first()
    active = bool(rec and rec.status == "active" and rec.device_id == device_id)
    return {"active": active, "revoked": not active}


#----------------------------- Device Claiming -----------------------------

@app.post("/api/claim")
def claim_device(
    payload: ClaimRequest,
    db: Session = Depends(get_db)
):
    api_key = db.query(ApiKey).filter(
        ApiKey.key == payload.api_key,
        ApiKey.status == "active"
    ).first()

    if not api_key:
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")

    if api_key.device_id is None:
        # ✅ First time claim — bind device & set bound_at
        api_key.device_id = payload.machine_id
        api_key.bound_at = datetime.utcnow()
        api_key.label = payload.description  # still fine for ApiKey

        # ✅ Also create entry in device_status table
        status = DeviceStatus(
            device_id=payload.machine_id,
            user_id=api_key.user_id,
            label=payload.description,
            last_seen=int(time.time()),
            
        )
        db.add(status)

        db.commit()

        logging.info(
            f"API key {api_key.key} bound to device {payload.machine_id} at {api_key.bound_at}."
        )

        return {
            "status": "bound",
            "message": f"Key bound to {payload.machine_id} at {api_key.bound_at}."
        }

    elif api_key.device_id == payload.machine_id:
        return {
            "status": "ok",
            "message": "Device already bound — everything ok."
        }

    else:
        raise HTTPException(
            status_code=403,
            detail=f"Key already bound to {api_key.device_id}."
        )



# ----------------------------- Dashboard & Summary -----------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    statuses = db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "statuses": statuses, "now": int(time.time()), "user": current_user
    })


# ----------------------------- Summary with Paddle Management URLs -----------------------------



@app.get("/summary", response_class=HTMLResponse)
async def summary(
    request: Request,
    device_label: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Epoch helpers (keep comparisons epoch vs epoch for index use)
    now_epoch = func.extract('epoch', func.now())
    five_min_ago = now_epoch - 300  # 5 minutes

    # Labels for the dropdown
    labels = (
        db.query(DeviceStatus.label)
          .filter(DeviceStatus.user_id == current_user.id)
          .distinct()
          .order_by(DeviceStatus.label)
          .all()
    )

    # Base telemetry query
    query = (
        db.query(DeviceData)
          .join(
              DeviceStatus,
              DeviceData.device_id == DeviceStatus.device_id
          )
          .filter(DeviceStatus.user_id == current_user.id)
    )

    # Optional label filter → resolve to device_id
    device_id_match = None
    if device_label:
        device_id_match = (
            db.query(DeviceStatus.device_id)
              .filter(
                  DeviceStatus.user_id == current_user.id,
                  DeviceStatus.label == device_label,
              )
              .scalar()
        )
    if device_id_match:
        query = query.filter(DeviceData.device_id == device_id_match)

    # Latest records + label
    records = (
        query.with_entities(DeviceData, DeviceStatus.label)
             .order_by(DeviceData.timestamp.desc())
             .limit(100)
             .all()
    )

    # Last-seen map (epoch) — make left side explicit
    last_seen_map = dict(
        db.query(DeviceData.device_id, func.max(DeviceData.timestamp))
          .select_from(DeviceData)
          .join(
              DeviceStatus,
              and_(
                  DeviceStatus.device_id == DeviceData.device_id,
                  DeviceStatus.user_id == current_user.id
              )
          )
          .group_by(DeviceData.device_id)
          .all()
    )

    # Registered devices (active keys; bound only)
    device_count = (
        db.query(func.count(func.distinct(ApiKey.device_id)))
          .filter(
              ApiKey.user_id == current_user.id,
              ApiKey.status == "active",
              ApiKey.revoked_at.is_(None),
              ApiKey.device_id.isnot(None),
          )
          .scalar()
        or 0
    )

    # Online stats
    ONLINE_WINDOW_SECS = 120  # 2 min window
    total_devices = (
        db.query(func.count())
          .select_from(DeviceStatus)
          .filter(DeviceStatus.user_id == current_user.id)
          .scalar()
        or 0
    )
    online_devices = (
        db.query(func.count())
          .select_from(DeviceStatus)
          .filter(
              DeviceStatus.user_id == current_user.id,
              # last_seen stored as epoch seconds
              DeviceStatus.last_seen >= now_epoch - ONLINE_WINDOW_SECS,
          )
          .scalar()
        or 0
    )

    # Activity metrics — epoch vs epoch
    msgs_last_5m = (
        db.query(func.count())
          .select_from(DeviceData)
          .filter(
              DeviceData.user_id == current_user.id,
              DeviceData.timestamp >= five_min_ago
          )
          .scalar()
        or 0
    )

    # Top talkers (label if present; explicit left side + OUTER JOIN)
    name_expr = func.coalesce(DeviceStatus.label, DeviceData.device_id).label("name")
    top_talkers = (
        db.query(name_expr, func.count().label("cnt"))
          .select_from(DeviceData)
          .outerjoin(
              DeviceStatus,
              and_(
                  DeviceStatus.device_id == DeviceData.device_id,
                  DeviceStatus.user_id == current_user.id
              )
          )
          .filter(
              DeviceData.user_id == current_user.id,
              DeviceData.timestamp >= five_min_ago
          )
          .group_by(name_expr)
          .order_by(text("cnt DESC"))
          .limit(5)
          .all()
    )

    # Subscription management (unchanged)
    sub_id = db.execute(text("""
        SELECT b.id
        FROM public.customers a
        JOIN public.subscriptions b ON a.id = b.customer_id
        WHERE b.status = 'active' AND a.email = :email
    """), {"email": current_user.email}).scalar()

    cancel_url = update_pm_url = None
    if sub_id:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://sandbox-api.paddle.com/subscriptions/{sub_id}",
                headers={"Authorization": f"Bearer {os.getenv('PADDLE_API_KEY')}"}
            )
        payload = resp.json()
        logging.info(f"Paddle subscription payload for {sub_id}: {payload}")
        m_urls = payload.get("data", {}).get("management_urls", {})
        cancel_url = m_urls.get("cancel")
        update_pm_url = m_urls.get("update_payment_method")

    # Render
    return templates.TemplateResponse("summary.html", {
        "request": request,
        "user": current_user,

        "records": records,
        "labels": [row.label for row in labels if row.label],
        "device_label": device_label,

        "device_count": device_count,
        "last_seen_map": last_seen_map,

        "total_devices": total_devices,
        "online_devices": online_devices,
        "online_window_secs": ONLINE_WINDOW_SECS,

        "msgs_last_5m": msgs_last_5m,
        "top_talkers": top_talkers,

        "cancel_url": cancel_url,
        "update_pm_url": update_pm_url,

        "now_ts": datetime.utcnow(),  # handy in templates
    })



   #----------------------------- Summary Data API -----------------------------
   #                                   
@app.get("/api/summary-data")
async def summary_data(device_label: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = (
        db.query(DeviceData, DeviceStatus.label)
        .join(DeviceStatus, DeviceData.device_id == DeviceStatus.device_id)
        .filter(DeviceStatus.user_id == current_user.id)
    )
    if device_label:
        query = query.filter(DeviceStatus.label == device_label)

    records = (
        query.order_by(DeviceData.timestamp.desc())
        .limit(100)
        .all()
    )

    def serialize(row):
        device_data, label = row
        return {
            "id": device_data.id,
            "device_id": device_data.device_id,
            "label": label,
            "data": device_data.data,
            "timestamp": device_data.timestamp,
        }

    return [serialize(r) for r in records]




# @app.get("/summary", response_class=HTMLResponse)
# def summary(
#     request: Request,
#     device_id: str = None,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     query = db.query(DeviceData).join(DeviceStatus, DeviceData.device_id == DeviceStatus.device_id)\
#              .filter(DeviceStatus.user_id == current_user.id)
#     if device_id:
#         query = query.filter(DeviceData.device_id == device_id)
#     records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()
#     return templates.TemplateResponse("summary.html", {
#         "request": request, "records": records, "filter_id": device_id
#     })


# ----------------------------- CSV Export & Devices -----------------------------
@app.get("/export")
def export_csv(device_id: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    device_ids = [
        d.device_id for d in db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id)
    ]
    query = db.query(DeviceData).filter(DeviceData.device_id.in_(device_ids))
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).all()

    def generate():
        data   = StringIO()
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


# Devices claiming/labeling omitted for brevity but unchanged…

# ----------------------------- Legal & Landing -----------------------------
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
    current_user: User = Depends(get_current_user_optional),
):
    subscription_status = None
    if current_user:
        result = db.execute(
            text("SELECT has_active_subscription(:email)"),
            {"email": current_user.email},
        ).scalar()
        subscription_status = result.lower() if result else None

        if subscription_status in ("active", "trialing"):
            response = RedirectResponse("/summary", status_code=302)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            return response

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


# ----------------------------- Paddle Webhook -----------------------------
app.include_router(paddle_router)

# ----------------------------- API Management Page -----------------------------


@app.get("/api-management", response_class=HTMLResponse)
def api_management(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Join ApiKey with DeviceStatus to get label
    # api_keys = (
    #     db.query(ApiKey.device_id, ApiKey.api_key, ApiKey.active, ApiKey.created_at, DeviceStatus.label)
    #     .join(DeviceStatus, ApiKey.device_id == DeviceStatus.device_id)
    #     .filter(ApiKey.user_id == current_user.id)
    #     .order_by(ApiKey.created_at.desc())
    #     .all()
    # )

    #- Fetch API keys with device labels

    api_keys = (
    db.query(
        ApiKey.device_id,
        ApiKey.key.label("key"),
        ApiKey.status,
        ApiKey.created_at,
        DeviceStatus.label.label("label"),
        ApiKey.id.label("id")  # Needed for revocation logic
     )
    .outerjoin(DeviceStatus, ApiKey.device_id == DeviceStatus.device_id)
    .filter(ApiKey.user_id == current_user.id)
    .order_by(ApiKey.created_at.desc())
    .all()
    )




    # Paddle subscription check (unchanged)
    sub_id = db.execute(text("""
        SELECT b.id
          FROM public.customers a
          JOIN public.subscriptions b ON a.id = b.customer_id
         WHERE b.status = 'active' AND a.email = :email
    """), {"email": current_user.email}).scalar()

    cancel_url = update_pm_url = None
    if sub_id:
        import httpx, os
        import asyncio
        async def fetch_urls():
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://sandbox-api.paddle.com/subscriptions/{sub_id}",
                    headers={"Authorization": f"Bearer {os.getenv('PADDLE_API_KEY')}"}
                )
                payload = resp.json()
                urls = payload.get("data", {}).get("management_urls", {})
                return urls.get("cancel"), urls.get("update_payment_method")
        cancel_url, update_pm_url = asyncio.run(fetch_urls())

    # Return with updated context
    return templates.TemplateResponse(
        "api-management.html",
        {
            "request": request,
            "api_keys": api_keys,
            "cancel_url": cancel_url,
            "update_pm_url": update_pm_url,
            "user": current_user
        }
    )


#----------------------------- API Key Creation -----------------------------



@app.get("/api-management/create")
def create_api_key(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_key = ApiKey(
        user_id=current_user.id,
        key=token_hex(16),  # generates a 32-char hex string
        status="active"
    )
    db.add(new_key)
    db.commit()
    return RedirectResponse("/api-management", status_code=302)

#----------------------------- API Key Revocation -----------------------------

@app.post("/api-management/revoke/{key_id}")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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


#----------------------------- Cleanup Old Device Data -----------------------------


def delete_old_device_data(db: Session, days: int = 7):
    cutoff = int((datetime.utcnow() - timedelta(days=days)).timestamp())
    deleted = db.query(DeviceData).filter(DeviceData.timestamp < cutoff).delete()
    db.commit()
    print(f"🧹 Deleted {deleted} rows older than {days} days from device_data.")



    # ---------- DOWNLOADS (robust) ----------


# 1) Mount for static access (e.g., /downloads/changelog.html)
app.mount("/downloads", StaticFiles(directory=str(DOWNLOADS_DIR)), name="downloads")

# 2) Human downloads page
@app.get("/downloads", name="downloads_page", response_class=HTMLResponse)
def downloads_page(request: Request):
    xml_path = DOWNLOADS_DIR / "update.xml"
    exe_path = DOWNLOADS_DIR / "SigStreamAgent-Setup.exe"

    version = "1.0.0.0"
    checksum_value = ""
    changelog_url = "/downloads/changelog.html"
    download_available = False
    size_str = "—"
    released_str = "—"

    if xml_path.exists():
        try:
            root = ET.parse(str(xml_path)).getroot()
            version = (root.findtext("version") or version).strip()
            checksum = (root.findtext("checksum") or "").strip()
            checksum_value = checksum.split(":", 1)[1] if checksum.lower().startswith("sha256:") else checksum
            chlog = (root.findtext("changelog") or "").strip()
            if chlog:
                changelog_url = chlog
        except Exception:
            pass

    if exe_path.exists():
        download_available = True
        stat = exe_path.stat()
        size_str = f"{stat.st_size / (1024*1024):.1f} MB"
        released_str = dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

    return templates.TemplateResponse("downloads.html", {
        "request": request,
        "version": version,
        "checksum": checksum_value,
        "exe_url": "/downloads/SigStreamAgent-Setup.exe",
        "download_available": download_available,
        "size_str": size_str,
        "released_str": released_str,
        "changelog_url": changelog_url,
        "ms_store_url": None,
    })

# 3) Strong headers for the two important files
@app.get("/downloads/update.xml")
def get_update_manifest():
    path = DOWNLOADS_DIR / "update.xml"
    if not path.exists():
        return HTMLResponse("update.xml not found", status_code=404)
    return FileResponse(str(path), media_type="application/xml",
                        headers={"Cache-Control": "no-store, must-revalidate",
                                 "X-Content-Type-Options": "nosniff"})

@app.get("/downloads/SigStreamAgent-Setup.exe")
def get_installer():
    path = DOWNLOADS_DIR / "SigStreamAgent-Setup.exe"
    if not path.exists():
        return HTMLResponse("installer not found", status_code=404)
    return FileResponse(str(path), media_type="application/octet-stream",
                        filename="SigStreamAgent-Setup.exe",
                        headers={"Cache-Control": "public, max-age=3600",
                                 "X-Content-Type-Options": "nosniff",
                                 "Accept-Ranges": "bytes"})
# ---------- /DOWNLOADS ----------



 