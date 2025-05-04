from fastapi import FastAPI, HTTPException, Request
from models import DeviceDataIn
from crud import insert_data
import time
import os
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi import Request
from database import SessionLocal
from models import DeviceData

templates = Jinja2Templates(directory="templates")







# Load environment variables from .env
load_dotenv()

# Get API key from .env or use a default (for dev)
API_KEY = os.getenv("SIGSTREAM_API_KEY", "mytestkey")

app = FastAPI()

@app.post("/data")
def receive_data(request: Request, payload: DeviceDataIn):
    auth = request.headers.get("Authorization")

    # Verify API key
    if not auth or auth.replace("Bearer ", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    ts = payload.timestamp or int(time.time())

    try:
        insert_data(payload.device_id, payload.data, ts)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, device_id: str = None):
    db = SessionLocal()
    query = db.query(DeviceData)
    if device_id:
        query = query.filter(DeviceData.device_id == device_id)
    records = query.order_by(DeviceData.timestamp.desc()).limit(100).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "records": records,
        "filter_id": device_id
    })


@app.get("/")
def health_check():
    return {"message": "SigStream Cloud API is up!"}
