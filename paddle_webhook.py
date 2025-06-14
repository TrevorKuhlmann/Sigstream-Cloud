import os
import logging
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from handlers import dispatch_event

router = APIRouter()

TEST_MODE = os.getenv("TEST_MODE", "0") == "1"

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        body = await request.body()
        json_data = await request.json()

        event_type = json_data.get("event_type") or json_data.get("eventType")

        if not event_type:
            logging.error("❌ Missing event_type in webhook payload")
            return {"detail": "Missing event_type"}

        if TEST_MODE:
            logging.warning("⚠️ Bypassing signature verification (TEST MODE)")
        else:
            # Add production signature check logic here when needed
            logging.info("🔒 Signature check would go here")

        logging.info(f"🔔 Received event: {event_type}")

        # Dispatch to appropriate handler
        await dispatch_event(event_type, json_data, db)

        return {"detail": "Webhook processed"}
    except Exception as e:
        logging.error("❌ Webhook processing failed", exc_info=True)
        return {"detail": f"Webhook failed: {str(e)}"}
