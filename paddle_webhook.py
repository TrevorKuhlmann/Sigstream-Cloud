from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import os, logging

from paddle_billing.Notifications import Verifier, Secret, NotificationEvent
from database import get_db
from handlers import dispatch_event

router = APIRouter()
secret_val = os.getenv("PADDLE_WEBHOOK_SECRET", "")
verifier = Verifier()
secret = Secret(secret_val)

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    sig = request.headers.get("Paddle-Signature")

    if not sig or not secret_val:
        logging.warning("⚠️ Skipping verification (TEST MODE)")
        raw = await request.json()
        evt = NotificationEvent(**raw)
        await dispatch_event(evt, db)
        return JSONResponse({"success": True})

    try:
        if not verifier.verify(request, secret):
            raise HTTPException(400, "Invalid signature")
        notif = NotificationEvent.from_request(request)
        await dispatch_event(notif, db)
        return JSONResponse({"success": True})

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Webhook processing failed")
        raise HTTPException(400, f"Webhook failed: {e}")
