from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import os

from paddle_billing.Notifications import Secret, Verifier
from paddle_billing.Entities.Notifications import NotificationEvent

from database import get_db
from handlers import dispatch_event  # Import the central dispatcher

router = APIRouter()

# Paddle webhook secret (e.g., from .env or Render environment)
PADDLE_WEBHOOK_SECRET = os.getenv("PADDLE_WEBHOOK_SECRET")
if not PADDLE_WEBHOOK_SECRET:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET is not set")

verifier = Verifier()
secret = Secret(PADDLE_WEBHOOK_SECRET)

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    # 1. Get raw body and headers
    body = await request.body()
    headers = request.headers

    # 2. Reconstruct into Paddle-style request
    signature = headers.get("Paddle-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Paddle-Signature")

    # 3. Use SDK to verify
    try:
        # Construct pseudo-Request object like the SDK expects
        from paddle_billing.HttpAdapters.FastAPI import FastAPIRequestAdapter
        wrapped = FastAPIRequestAdapter(request, raw_body=body)

        if not verifier.verify(wrapped, secret):
            raise HTTPException(status_code=400, detail="Invalid signature")

        notification = NotificationEvent.from_request(wrapped)
        logging.info("🔐 Verified Paddle event: %s", notification.event_type)

        # 4. Dispatch to proper handler
        await dispatch_event(notification, db)

        return JSONResponse({"success": True})

    except Exception as e:
        logging.exception("Webhook verification failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
