import logging
from sqlalchemy.orm import Session
from paddle_billing.Entities.Notifications import NotificationEvent

from models import Customer, Subscription
from datetime import datetime
import json

def parse_datetime(dt: str | None) -> datetime | None:
    return datetime.fromisoformat(dt.replace("Z", "+00:00")) if dt else None

# Individual event handlers
async def handle_customer_created(event: NotificationEvent, db: Session):
    data = event.data
    if not db.get(Customer, data.id):
        db.add(Customer(id=data.id, email=data.email))
        db.commit()
        logging.info(f"👤 Customer created: {data.id} ({data.email})")

async def handle_subscription_created(event: NotificationEvent, db: Session):
    data = event.data
    email = None

    # Extract email from passthrough if available
    raw_pt = data.passthrough
    if raw_pt:
        try:
            pt = json.loads(raw_pt)
            email = pt.get("email")
        except json.JSONDecodeError:
            logging.warning("Invalid passthrough JSON in subscription.created")

    customer = db.get(Customer, data.customer_id)
    if not customer:
        customer = Customer(id=data.customer_id, email=email or f"{data.customer_id}@placeholder.local")
        db.add(customer)
    else:
        if email and customer.email.endswith("@placeholder.local"):
            customer.email = email

    sub = db.get(Subscription, data.id)
    if not sub:
        sub = Subscription(
            id=data.id,
            customer_id=data.customer_id,
            status=data.status,
            started_at=parse_datetime(data.created_at),
            next_billed_at=parse_datetime(data.next_billed_at),
        )
        db.add(sub)
    else:
        sub.status = data.status
        sub.next_billed_at = parse_datetime(data.next_billed_at)

    db.commit()
    logging.info(f"📦 Subscription created: {data.id} -> {data.status}")

async def handle_subscription_updated(event: NotificationEvent, db: Session):
    data = event.data
    sub = db.get(Subscription, data.id)
    if sub:
        sub.status = data.status or sub.status
        sub.next_billed_at = parse_datetime(data.next_billed_at)
        if data.canceled_at:
            sub.canceled_at = parse_datetime(data.canceled_at)
        db.commit()
        logging.info(f"🔁 Subscription updated: {sub.id} -> {sub.status}")

async def handle_subscription_canceled(event: NotificationEvent, db: Session):
    data = event.data
    sub = db.get(Subscription, data.id)
    if sub:
        sub.status = "canceled"
        if data.canceled_at:
            sub.canceled_at = parse_datetime(data.canceled_at)
        db.commit()
        logging.info(f"❌ Subscription canceled: {sub.id}")

async def handle_subscription_expired(event: NotificationEvent, db: Session):
    data = event.data
    sub = db.get(Subscription, data.id)
    if sub:
        sub.status = "expired"
        db.commit()
        logging.info(f"⌛ Subscription expired: {sub.id}")

async def handle_checkout_completed(event: NotificationEvent, db: Session):
    data = event.data
    cust = data.customer
    cust_id = cust.id
    email = cust.email

    if not db.get(Customer, cust_id):
        db.add(Customer(id=cust_id, email=email))
    else:
        customer = db.get(Customer, cust_id)
        if email and customer.email.endswith("@placeholder.local"):
            customer.email = email

    db.commit()
    logging.info(f"🛒 Checkout completed: {cust_id} ({email})")


# Routing map
event_router = {
    "customer.created": handle_customer_created,
    "subscription.created": handle_subscription_created,
    "subscription.updated": handle_subscription_updated,
    "subscription.canceled": handle_subscription_canceled,
    "subscription.expired": handle_subscription_expired,
    "checkout.completed": handle_checkout_completed,
}

# Dispatcher
async def dispatch_event(event: NotificationEvent, db: Session):
    handler = event_router.get(event.event_type)
    if handler:
        await handler(event, db)
    else:
        logging.info(f"⚠️ No handler for event: {event.event_type}")
