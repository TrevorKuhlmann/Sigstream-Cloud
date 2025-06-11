from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import logging
import os
import json

from paddle_billing.Entities.Notifications import NotificationEvent
from database import get_db
from handlers import dispatch_event  # Your central dispatcher

router = APIRouter()

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        # 🚫 TEMP: Signature verification disabled for regression testing
        body = await request.body()
        payload = json.loads(body)

        logging.warning("⚠️ Bypassing signature verification (TEST MODE)")
        notification = NotificationEvent.from_dict(payload)

        logging.info(f"🔔 Received event: {notification.event_type}")
        await dispatch_event(notification, db)

        return JSONResponse({"success": True})

    except Exception as e:
        logging.exception("Webhook processing failed")
        raise HTTPException(status_code=400, detail=f"Webhook failed: {str(e)}")
