from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import os, logging

##from paddle_billing.entities.
from paddle_billing.Notifications import Secret, Verifier
from paddle_billing.entities.http import Request as PaddleRequest
from paddle_billing.entities.notifications import NotificationEvent

from database import get_db
from handlers import dispatch_event

router = APIRouter()

secret_val = os.getenv("PADDLE_WEBHOOK_SECRET")
if not secret_val:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET not set")
secret = Secret(secret_val)
verifier = Verifier()

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    sig = request.headers.get("Paddle-Signature")
    if not sig:
        logging.warning("⚠️ Bypassing signature verification (TEST MODE)")
        payload = await request.json()
        await dispatch_event(NotificationEvent(**payload), db)
        return JSONResponse({"success": True})

    try:
        paddlereq = PaddleRequest(body=body, headers={"Paddle-Signature": sig})
        if not verifier.verify(paddlereq, secret):
            raise HTTPException(400, "Invalid signature")

        notification = NotificationEvent.from_request(paddlereq)
        await dispatch_event(notification, db)
        return JSONResponse({"success": True})

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Webhook processing failed")
        raise HTTPException(400, f"Webhook failed: {e}")
