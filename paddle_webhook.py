from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import os

from paddle_billing.HttpAdapters.FastAPI import FastAPIRequestAdapter
from paddle_billing.Notifications import Secret, Verifier
from paddle_billing.Entities.Notifications import NotificationEvent

from database import get_db
from handlers import dispatch_event  # your event dispatcher

router = APIRouter()

# Load Paddle webhook secret
PADDLE_WEBHOOK_SECRET = os.getenv("PADDLE_WEBHOOK_SECRET")
if not PADDLE_WEBHOOK_SECRET:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET is not set")

secret = Secret(PADDLE_WEBHOOK_SECRET)
verifier = Verifier()

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        # Wrap FastAPI request in Paddle's expected format
        raw_body = await request.body()
        adapter = FastAPIRequestAdapter(request, raw_body=raw_body)

        # Verify webhook signature
        if not verifier.verify(adapter, secret):
            raise HTTPException(status_code=400, detail="Invalid Paddle signature")

        # Deserialize event
        notification = NotificationEvent.from_request(adapter)
        logging.info(f"🔐 Verified event: {notification.event_type}")

        # Dispatch to internal event handler
        await dispatch_event(notification, db)

        return JSONResponse({"success": True})

    except Exception as e:
        logging.exception("Webhook verification failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
