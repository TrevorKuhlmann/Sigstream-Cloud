from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from paddle_billing import Verifier, Secret
from paddle_billing.Entities.Notifications import NotificationEvent

import os
import logging

from database import get_db
from handlers import dispatch_event

router = APIRouter()

# Load secret
PADDLE_WEBHOOK_SECRET = os.getenv("PADDLE_WEBHOOK_SECRET")
if not PADDLE_WEBHOOK_SECRET:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET is not set")

verifier = Verifier()
secret = Secret(PADDLE_WEBHOOK_SECRET)

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        # 1. Grab raw body and signature
        raw_body = await request.body()
        signature = request.headers.get("Paddle-Signature")

        if not signature:
            raise HTTPException(status_code=400, detail="Missing Paddle-Signature header")

        # 2. Build verification payload
        request_like = {
            "body": raw_body,
            "headers": {
                "Paddle-Signature": signature
            }
        }

        if not verifier.verify(request_like, secret):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

        # 3. Parse the notification event
        notification = NotificationEvent.from_dict(
            body=raw_body,
            headers=request_like["headers"]
        )

        logging.info(f"🔐 Verified Paddle webhook: {notification.event_type}")
        await dispatch_event(notification, db)

        return JSONResponse({"success": True})

    except Exception as e:
        logging.exception("Webhook processing failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
