from fastapi import Request, Depends, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime
import logging
import json

from database import get_db
from models import Customer, Subscription

router = APIRouter()

def parse_datetime(dt: str | None) -> datetime | None:
    return datetime.fromisoformat(dt.replace("Z", "+00:00")) if dt else None

@router.post("/paddle-webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    logging.info("🔍 Full Paddle payload: %s", payload)
    event = payload.get("event_type")
    if not event:
        raise HTTPException(400, "Missing event_type")

    handler = event_handlers.get(event)
    if handler:
        await handler(payload, db)
    else:
        logging.info(f"No handler for event {event}")

    return JSONResponse({"success": True})

# -- Handlers --

async def handle_customer_created(payload: dict, db: Session):
    data = payload["data"]
    customer = db.get(Customer, data["id"])
    if not customer:
        customer = Customer(id=data["id"], email=data.get("email"))
        db.add(customer)
        db.commit()

async def handle_subscription_created(payload: dict, db: Session):
    data = payload["data"]
    cust_id = data["customer_id"]

    # Extract email from passthrough (must be set in checkout)
    raw_pt = data.get("passthrough")
    email = None
    if raw_pt:
        try:
            pt = json.loads(raw_pt)
            email = pt.get("email")
        except json.JSONDecodeError:
            logging.warning("Invalid passthrough JSON")

    # Ensure customer exists with real email
    customer = db.get(Customer, cust_id)
    if not customer:
        customer = Customer(id=cust_id, email=email or f"{cust_id}@placeholder.local")
        db.add(customer)
    else:
        if email and customer.email.endswith("@placeholder.local"):
            customer.email = email

    # Upsert subscription
    sub = db.get(Subscription, data["id"])
    if not sub:
        sub = Subscription(
            id=data["id"],
            customer_id=cust_id,
            status=data["status"],
            started_at=parse_datetime(data.get("created_at")),
            next_billed_at=parse_datetime(data.get("next_billed_at"))
        )
        db.add(sub)
    else:
        sub.status = data["status"]
        sub.next_billed_at = parse_datetime(data.get("next_billed_at"))

    db.commit()
    logging.info(f"Subscription {sub.id} -> {sub.status} for {cust_id}")

async def handle_subscription_activated(payload: dict, db: Session):
    await handle_subscription_created(payload, db)

async def handle_subscription_cancelled(payload: dict, db: Session):
    data = payload["data"]
    cust_id = data.get("customer_id")
    if cust_id and not db.get(Customer, cust_id):
        db.add(Customer(id=cust_id, email=None))
    sub = db.get(Subscription, data["id"])
    if sub:
        sub.status = "canceled"
        db.commit()

async def handle_subscription_expired(payload: dict, db: Session):
    data = payload["data"]
    cust_id = data.get("customer_id")
    if cust_id and not db.get(Customer, cust_id):
        db.add(Customer(id=cust_id, email=None))
    sub = db.get(Subscription, data["id"])
    if sub:
        sub.status = "expired"
        db.commit()



async def handle_subscription_updated(payload: dict, db: Session):
     data = payload["data"]
     sub = db.get(Subscription, data["id"])
     if sub:
        sub.status = data.get("status", sub.status)
        sub.next_billed_at = parse_datetime(data.get("next_billed_at"))
        if data.get("canceled_at"):
            sub.canceled_at = parse_datetime(data["canceled_at"])
        db.commit()
        logging.info(f"🔁 Subscription updated: {sub.id} -> {sub.status}")


async def handle_subscription_canceled(payload: dict, db: Session):
    data = payload["data"]
    sub = db.get(Subscription, data["id"])
    if sub:
        sub.status = "canceled"
        if data.get("canceled_at"):
            sub.canceled_at = parse_datetime(data["canceled_at"])
        db.commit()
        logging.info(f"❌ Subscription canceled: {sub.id}")


# -- Routing --

event_handlers = {
    "subscription.updated":    handle_subscription_updated,
    "subscription.cancelled":  handle_subscription_canceled,
    "customer.created":       handle_customer_created,
    "subscription.created":   handle_subscription_created,
    "subscription.activated": handle_subscription_activated,
    "subscription.cancelled": handle_subscription_cancelled,
    "subscription.expired":   handle_subscription_expired,
}
