from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from models import DeviceDataIn, DeviceData, DeviceStatus
from crud import insert_data, update_heartbeat
from database import SessionLocal
from fastapi_utils.tasks import repeat_every
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi_utils.tasks import repeat_every
import logging
import logging
import time
import os

# Load environment variables
load_dotenv()
API_KEY = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")

# FastAPI setup
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")

##@app.on_event("startup")
@repeat_every(seconds=30)  # Run every 30 seconds
def check_for_offline_devices():
    db = SessionLocal()
    now = int(time.time())
    threshold = 90  # seconds offline

    inactive_devices = []
    for status in db.query(DeviceStatus).all():
        if now - status.last_seen > threshold:
            inactive_devices.append((status.device_id, now - status.last_seen))

    db.close()

    if inactive_devices:
        for device_id, age in inactive_devices:
            logging.warning(f"⚠️ Device '{device_id}' is offline for {age} seconds.")
    else:
        logging.info("✅ All devices are healthy.")

@app.post("/data")
def receive_data(request: Request, payload: DeviceDataIn):
    auth = request.headers.get("Authorization")

    if not auth or auth.replace("Bearer ", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    ts = payload.timestamp or int(time.time())

    try:
        insert_data(payload.device_id, payload.data, ts)
        update_heartbeat(payload.device_id, ts)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def health_check():
    return {"message": "SigStream Cloud API is up!"}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, device_id: str = None):
    db = SessionLocal()

    # Fetch latest device status
    statuses = db.query(DeviceStatus).all()
    last_seen_map = {s.device_id: s.last_seen for s in statuses}

    # Fetch recent data (filtered)
    query = db.query(DeviceData)
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()

    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "records": records,
        "filter_id": device_id,
        "last_seen_map": last_seen_map
    })
