# handlers.py (SDK-free version) bb
import logging
from sqlalchemy.orm import Session
from models import Customer, Subscription, Transaction
from datetime import datetime

logger = logging.getLogger(__name__)

def parse_datetime(dt_str):
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00")) if dt_str else None

def safe_get(d, *keys):
    for key in keys:
        d = d.get(key, {})
    return d if d else None

async def dispatch_event(event_type: str, payload: dict, db: Session):
    match event_type:
        case "customer.created":
            await handle_customer_created(payload, db)
        case "subscription.created":
            await handle_subscription_created(payload, db)
        case "transaction.paid":
            await handle_transaction_paid(payload, db)
        case _:
            logger.warning(f"\u26a0\ufe0f No handler for event: {event_type}")

async def handle_customer_created(data: dict, db: Session):
    obj = Customer(
        id=data["data"]["id"],
        email=data["data"].get("email"),
        name=data["data"].get("name"),
        country_code=safe_get(data, "data", "address", "country_code"),
        postcode=safe_get(data, "data", "address", "postal_code"),
    )
    db.merge(obj)
    db.commit()

async def handle_subscription_created(payload: dict, db: Session):
    customer_id = payload.get("customer_id")
    subscription_id = payload.get("id")

    # Ensure customer exists
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        email = payload.get("customer_email", "unknown@example.com")
        customer = Customer(id=customer_id, email=email)
        db.add(customer)
        db.commit()

    sub = Subscription(
        id=subscription_id,
        customer_id=customer_id,
        status=payload.get("status"),
        started_at=parse_datetime(payload.get("start_time")),
        ended_at=parse_datetime(payload.get("end_time")),
        next_billed_at=parse_datetime(payload.get("next_billed_time")),
        updated_at=parse_datetime(payload.get("updated_at")),
        canceled_at=parse_datetime(payload.get("canceled_at")),
    )
    db.add(sub)
    db.commit()
    logger.info(f"✅ Subscription created: {subscription_id}")

async def handle_transaction_paid(data: dict, db: Session):
    tx = Transaction(
        id=data["data"]["id"],
        customer_id=data["data"].get("customer_id"),
        subscription_id=data["data"].get("subscription_id"),
        status=data["data"].get("status"),
        amount=data["data"].get("amount"),
        currency=data["data"].get("currency_code"),
        tax_rate=data["data"].get("tax_rate"),
        paid_at=parse_datetime(data["data"].get("paid_at")),
    )
    db.merge(tx)
    db.commit()
