from fastapi import (
    FastAPI, HTTPException, Request, Depends, status, Body, Form, BackgroundTasks
)
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi_utils.tasks import repeat_every
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from datetime import datetime
from io import StringIO
from dotenv import load_dotenv
from jose import jwt
import os, time, csv, logging
from datetime import timedelta
from database import SessionLocal
from models import DeviceDataIn, DeviceData, DeviceStatus, User
from schemas import UserCreate, Token
from fastapi.responses import HTMLResponse

from fastapi import Request, BackgroundTasks, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from datetime import datetime, timedelta

from auth import create_access_token, get_db
from email_utils import send_magic_link_email
from models import User


from crud import insert_data, update_heartbeat
from auth import (
    get_current_user, hash_password, verify_password,
    create_access_token, create_magic_token
)
from email_utils import send_magic_link_email

# ----------------------------- Config -----------------------------

load_dotenv()
API_KEY = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")
SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret")
ALGORITHM = "HS256"

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters['format_ts'] = lambda ts: datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
logging.basicConfig(level=logging.INFO)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------------------- Magic Link Auth -----------------------------


@app.post("/magic-login-register", response_class=HTMLResponse)
async def magic_login_register(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()

    if user:
        # User already exists - do NOT register again, just inform
        return templates.TemplateResponse("magic_login.html", {
            "request": request,
            "error": "You're already registered. Please sign in instead."
        })

    # Register new user
    user = User(email=email, hashed_password="", customer_name="New User")
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create token valid for 10 minutes
    expire = datetime.utcnow() + timedelta(minutes=10)
    token = create_access_token(data={"sub": email}, expires_delta=timedelta(minutes=10))
    magic_link = f"{request.base_url}magic-auth?token={token}"

    # Send email
    background_tasks.add_task(send_magic_link_email, email, magic_link)

    return templates.TemplateResponse("check_email.html", {
        "request": request,
        "email": email,
        "message": "Check your inbox and click the magic link to log in."
    })

@app.post("/magic-login-signin")
async def magic_signin(request: Request, background_tasks: BackgroundTasks, email: str = Form(...)):
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    if not user:
        return templates.TemplateResponse("magic_login.html", {
            "request": request,
            "error": "No account found for this email. Please register first."
        })

    token = create_access_token(data={"sub": user.email}, expires_minutes=10)
    magic_link = f"{request.base_url}magic-auth?token={token}"
    background_tasks.add_task(send_magic_link_email, email, magic_link)

    return templates.TemplateResponse("check_email.html", {"request": request, "email": email})

@app.get("/magic-auth", response_class=HTMLResponse)
def complete_magic_login(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=400, detail="Invalid token")
    except JWTError:
        return HTMLResponse("Invalid or expired link", status_code=400)

    user = db.query(User).filter(User.email == email).first()
    if not user:
        return HTMLResponse("User not found", status_code=404)

    access_token = create_access_token(data={"sub": user.email})
    response = templates.TemplateResponse("plan_selection.html", {
        "request": request,
        "user_email": user.email
    })
    response.set_cookie("access_token", access_token, httponly=True)
    return response

# ----------------------------- Traditional Form Auth -----------------------------

@app.get("/register-form", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register-form")
def register_form_post(request: Request, email: str = Form(...), password: str = Form(...), customer_name: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email already registered"
        })
    new_user = User(email=email, hashed_password=hash_password(password), customer_name=customer_name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return RedirectResponse(url="/login-form", status_code=302)

@app.get("/login-form", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login-form")
def login_form_post(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid credentials"
        })
    token = create_access_token(data={"sub": user.email})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True)
    return response

# ----------------------------- Core API -----------------------------

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
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
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(data={"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/data")
def receive_data(payload: DeviceDataIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ts = payload.timestamp or int(time.time())
    insert_data(payload.device_id, payload.data, ts, db, current_user)
    update_heartbeat(payload.device_id, ts, db, current_user)
    return {"status": "success"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    statuses = db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "statuses": statuses, "now": int(time.time())
    })

@app.get("/summary", response_class=HTMLResponse)
def summary(request: Request, device_id: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(DeviceData).join(DeviceStatus, DeviceData.device_id == DeviceStatus.device_id)\
        .filter(DeviceStatus.user_id == current_user.id)
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()
    return templates.TemplateResponse("summary.html", {
        "request": request, "records": records, "filter_id": device_id
    })

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

# ----------------------------- Landing -----------------------------

from fastapi import Cookie  # at the top if not already imported

@app.get("/", response_class=HTMLResponse)
def landing_page(request: Request, token: str = Cookie(default=None), db: Session = Depends(get_db)):
    user_email = None

    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
            user = db.query(User).filter(User.email == email).first()
            if user:
                user_email = user.email
        except Exception as e:
            logging.warning(f"JWT decode failed: {e}")
            pass

    return templates.TemplateResponse("landing.html", {
        "request": request,
        "now": datetime.utcnow(),
        "user_email": user_email
    })
