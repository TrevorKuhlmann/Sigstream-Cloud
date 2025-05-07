from fastapi import FastAPI, HTTPException, Request
from datetime import datetime
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from models import DeviceDataIn, DeviceData, DeviceStatus
from crud import insert_data, update_heartbeat
from database import SessionLocal
from fastapi_utils.tasks import repeat_every
from contextlib import asynccontextmanager
from fastapi.responses import StreamingResponse
from database import Base, engine
import csv
from io import StringIO
import logging
import time
import os

# TEMP: Create tables in the new Postgres DB
import models
###Base.metadata.create_all(bind=engine)

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
# Add a Jinja2 filter to format Unix timestamps
def format_timestamp(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

templates.env.filters['format_ts'] = format_timestamp



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



@app.get("/db-check")
def db_check():
    try:
        db = SessionLocal()
        result = db.execute("SELECT 1").scalar()
        db.close()
        return {"db_status": "connected", "result": result}
    except Exception as e:
        return {"db_status": "error", "detail": str(e)}


#  Health check
@app.get("/health")
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


###sumary 
@app.get("/summary", response_class=HTMLResponse)
def summary(request: Request, device_id: str = None):
    db = SessionLocal()
    query = db.query(DeviceData)
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()
    db.close()

    return templates.TemplateResponse("summary.html", {
        "request": request,
        "records": records,
        "filter_id": device_id
    })


@app.get("/export")
def export_csv(device_id: str = None):
    db = SessionLocal()
    query = db.query(DeviceData)
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).all()
    db.close()

    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(["ID", "Device ID", "Data", "Timestamp"])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)

        for row in records:
            writer.writerow([row.id, row.device_id, row.data, row.timestamp])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    return StreamingResponse(generate(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=sigstream_export.csv"
    })

    print("DB ENGINE:", DATABASE_URL.split(":")[0])

