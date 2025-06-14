# paddle_webhook.py
from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import os

from paddle_billing.Notifications import Secret, Verifier, NotificationEvent
from database import get_db
from handlers import dispatch_event

router = APIRouter()

PADDLE_WEBHOOK_SECRET = os.getenv("PADDLE_WEBHOOK_SECRET")
TEST_MODE = os.getenv("TEST_MODE") == "1"

if not PADDLE_WEBHOOK_SECRET:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET is not set")

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("Paddle-Signature")

    if not TEST_MODE:
        if not signature:
            raise HTTPException(status_code=400, detail="Missing Paddle-Signature")

        verifier = Verifier()
        secret = Secret(PADDLE_WEBHOOK_SECRET)
        if not verifier.verify(body, signature, secret):
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        logging.warning("\u26a0\ufe0f Bypassing signature verification (TEST MODE)")

    try:
        event = NotificationEvent.from_request(body, signature)
        logging.info("\ud83d\udd14 Received event: %s", event.name)
        await dispatch_event(event, db)
        return JSONResponse({"success": True})
    except Exception as e:
        logging.exception("Webhook processing failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
