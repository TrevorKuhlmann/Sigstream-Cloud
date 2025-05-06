from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from models import DeviceDataIn, DeviceData, DeviceStatus
from crud import insert_data, update_heartbeat
from database import SessionLocal
from fastapi_utils.tasks import repeat_every
from contextlib import asynccontextmanager
import logging
import time
import os

# Load env variables
load_dotenv()
API_KEY = os.getenv("SIGSTREAM_API_KEY", "mysecretapikey123")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# FastAPI app with modern lifespan handling
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


#  Background check for offline devices
@repeat_every(seconds=30)
def check_for_offline_devices():
    db = SessionLocal()
    now = int(time.time())
    threshold = 90  # seconds idle
    inactive_devices = []

    for status in db.query(DeviceStatus).all():
        if now - status.last_seen > threshold:
            inactive_devices.append((status.device_id, now - status.last_seen))

    db.close()

    if inactive_devices:
        for device_id, age in inactive_devices:
            logging.warning(f" Device '{device_id}' is offline for {age} seconds.")
    else:
        logging.info(" All devices are healthy.")


#  Secure data receiver with auth
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


#  Health check
@app.get("/")
def health_check():
    return {"message": "SigStream Cloud API is up!"}


#  Device heartbeat dashboard
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    db = SessionLocal()
    statuses = db.query(DeviceStatus).all()
    db.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "statuses": statuses,
        "now": int(time.time())
    })
