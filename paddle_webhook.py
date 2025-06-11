from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import os

from paddle_billing.Notifications import Secret, Verifier
from paddle_billing.Entities.Notifications import NotificationEvent

from database import get_db
from handlers import dispatch_event

router = APIRouter()

PADDLE_WEBHOOK_SECRET = os.getenv("PADDLE_WEBHOOK_SECRET")
if not PADDLE_WEBHOOK_SECRET:
    raise RuntimeError("PADDLE_WEBHOOK_SECRET is not set")

verifier = Verifier()
secret = Secret(PADDLE_WEBHOOK_SECRET)

# 👇 Custom request adapter to match what SDK expects
class RawRequestAdapter:
    def __init__(self, headers: dict, body: bytes):
        self.headers = headers
        self.body = body

    def get_header(self, name: str) -> str | None:
        return self.headers.get(name)

    def get_body(self) -> bytes:
        return self.body

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.body()
        headers = dict(request.headers)

        wrapped_request = RawRequestAdapter(headers, body)

        if not verifier.verify(wrapped_request, secret):
            raise HTTPException(status_code=400, detail="Invalid signature")

        notification = NotificationEvent.from_request(wrapped_request)
        logging.info("🔐 Verified Paddle event: %s", notification.event_type)

        await dispatch_event(notification, db)
        return JSONResponse({"success": True})

    except Exception as e:
        logging.exception("Webhook verification failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
