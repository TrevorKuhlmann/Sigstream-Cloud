from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from database import get_db
from . import models

router = APIRouter()

def parse_datetime(dt: str | None) -> datetime | None:
    return datetime.fromisoformat(dt.replace("Z", "+00:00")) if dt else None

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    event_type = payload.get("event_type")

    if not event_type:
        raise HTTPException(status_code=400, detail="Missing event_type")

    handler = event_handlers.get(event_type)
    if handler:
        await handler(payload, db)
    else:
        logging.warning(f"Unhandled Paddle event: {event_type}")

    return JSONResponse(content={"success": True}, status_code=200)

# -------------------------
# Event Handlers
# -------------------------

async def handle_customer_created(payload: dict, db: Session):
    data = payload["data"]
    customer_id = data["id"]

    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        customer = models.Customer(
            id=customer_id,
            email=data.get("email"),
        )
        db.add(customer)
        db.commit()

async def handle_subscription_created(payload: dict, db: Session):
    data = payload["data"]
    sub = db.query(models.Subscription).get(data["id"])

    if not sub:
        sub = models.Subscription(
            id=data["id"],
            customer_id=data["customer_id"],
            status=data["status"],
            next_billed_at=parse_datetime(data.get("next_billed_at")),
        )
        db.add(sub)
    else:
        sub.status = data["status"]
        sub.next_billed_at = parse_datetime(data.get("next_billed_at"))

    db.commit()

async def handle_subscription_activated(payload: dict, db: Session):
    await handle_subscription_created(payload, db)

async def handle_subscription_cancelled(payload: dict, db: Session):
    data = payload["data"]
    sub = db.query(models.Subscription).get(data["id"])
    if sub:
        sub.status = "cancelled"
        db.commit()

async def handle_subscription_expired(payload: dict, db: Session):
    data = payload["data"]
    sub = db.query(models.Subscription).get(data["id"])
    if sub:
        sub.status = "expired"
        db.commit()

# -------------------------
# Event Routing
# -------------------------

event_handlers = {
    "customer.created": handle_customer_created,
    "subscription.created": handle_subscription_created,
    "subscription.activated": handle_subscription_activated,
    "subscription.cancelled": handle_subscription_cancelled,
    "subscription.expired": handle_subscription_expired,
}
