from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import os

from paddle_billing.Entities.Notifications import NotificationEvent
from paddle_billing.Notifications import Verifier, Secret

from database import get_db
from handlers import dispatch_event

router = APIRouter()

PADDLE_WEBHOOK_SECRET = os.getenv("PADDLE_WEBHOOK_SECRET")
if not PADDLE_WEBHOOK_SECRET:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET is not set")

verifier = Verifier()
secret = Secret(PADDLE_WEBHOOK_SECRET)

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.body()
        headers = dict(request.headers)

        # 🔧 Test mode toggleff
        if os.getenv("TEST_MODE") == "1":
            logging.warning("⚠️ Bypassing signature verification (TEST MODE)")
            notification = NotificationEvent.from_json(body.decode("utf-8"))
        else:
            signature = headers.get("Paddle-Signature")
            if not signature:
                raise HTTPException(status_code=400, detail="Missing Paddle-Signature")

            if not verifier.verify_raw(body, signature, secret):
                raise HTTPException(status_code=400, detail="Invalid signature")

            notification = NotificationEvent.from_json(body.decode("utf-8"))

        logging.info(f"🔔 Received event: {notification.event_type}")
        await dispatch_event(notification, db)
        return JSONResponse({"success": True})

    except Exception as e:
        logging.exception("Webhook processing failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
