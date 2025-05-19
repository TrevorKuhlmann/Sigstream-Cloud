from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from fastapi_utils.tasks import repeat_every
from contextlib import asynccontextmanager
from datetime import datetime
from io import StringIO
from dotenv import load_dotenv
import logging, time, os, csv
from auth import get_current_user

from database import SessionLocal
from models import DeviceDataIn, DeviceData, DeviceStatus, User
from schemas import UserCreate, Token
from crud import insert_data, update_heartbeat
from auth import hash_password, verify_password, create_access_token, get_current_user

from fastapi import Body
from auth import get_current_user
from fastapi import Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles



# Load .env
load_dotenv()
API_KEY = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")

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

from auth import get_current_user  # ensure this is imported

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    statuses = db.query(DeviceStatus).filter(DeviceStatus.user_id == current_user.id).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "statuses": statuses,
        "now": int(time.time())
    })


@app.get("/summary", response_class=HTMLResponse)
def summary(request: Request, device_id: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(DeviceData).join(DeviceStatus, DeviceData.device_id == DeviceStatus.device_id)\
        .filter(DeviceStatus.user_id == current_user.id)

    if device_id:
        query = query.filter(DeviceData.device_id == device_id)

    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()

    return templates.TemplateResponse("summary.html", {
        "request": request,
        "records": records,
        "filter_id": device_id
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
        yield data.getvalue()
        data.seek(0); data.truncate(0)
        for row in records:
            writer.writerow([row.id, row.device_id, row.data, row.timestamp])
            yield data.getvalue()
            data.seek(0); data.truncate(0)

    return StreamingResponse(generate(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=sigstream_export.csv"
    })

@app.get("/health")
def health_check():
    return {"message": "SigStream Cloud API is up!"}

@app.get("/db-check")
def db_check():
    try:
        db = SessionLocal()
        result = db.execute(text("SELECT 1")).scalar()
        db.close()
        return {"db_status": "connected", "result": result}
    except Exception as e:
        return {"db_status": "error", "detail": str(e)}

@repeat_every(seconds=30)
def check_for_offline_devices():
    db = SessionLocal()
    now = int(time.time())
    threshold = 90
    for status in db.query(DeviceStatus).all():
        if now - status.last_seen > threshold:
            logging.warning(f"Device '{status.device_id}' is offline for {now - status.last_seen} seconds.")
    db.close()

    

@app.post("/claim-device")
def claim_device(
    device_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    device = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id).first()
    
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.user_id is not None:
        raise HTTPException(status_code=400, detail="Device already claimed")

    device.user_id = current_user.id
    db.commit()
    return {"message": f"Device '{device_id}' claimed by user '{current_user.email}'"}

@app.get("/devices", response_class=HTMLResponse)
def device_management(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    devices = db.query(DeviceStatus).filter(DeviceStatus.user_id == user.id).all()
    return templates.TemplateResponse("devices.html", {
        "request": request,
        "devices": devices,
        "user": user
    })

@app.post("/devices/claim")
def claim_device(device_id: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    device = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.user_id is not None:
        raise HTTPException(status_code=400, detail="Device is already claimed")

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
def update_device_label(
    device_id: str = Form(...),
    new_label: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    device = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id, DeviceStatus.user_id == user.id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or not owned by you")

    device.label = new_label
    db.commit()
    return RedirectResponse(url="/devices", status_code=302)

@app.get("/", response_class=HTMLResponse)
def landing_page(request: Request):
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "now": datetime.now()
    })


# Serve register page
@app.get("/register-form", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

# Handle register form POST
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
            "request": request,
            "error": "Email already registered"
        })
    new_user = User(email=email, hashed_password=hash_password(password), customer_name=customer_name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return RedirectResponse(url="/login-form", status_code=302)

# Serve login page
@app.get("/login-form", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# Handle login form POST
@app.post("/login-form")
def login_form_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
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


@app.get("/", response_class=HTMLResponse)
def landing_page(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request, "now": datetime.utcnow()})

