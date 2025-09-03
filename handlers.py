import logging
from sqlalchemy.orm import Session
from models import Customer, Subscription, Transaction, PaymentMethod, Address
from utils import parse_datetime

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select
from utils import parse_datetime
from models import Subscription
import logging

# utils.py (or similar)
import os
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)


# -------------------- DISPATCHER --------------------

async def dispatch_event(event_type: str, payload: dict, db: Session):
    handler_map = {
        "customer.created": handle_customer_created,
        "subscription.created": handle_subscription_created,
        "transaction.paid": handle_transaction_paid,
        "transaction.created": handle_transaction_created,
        "transaction.updated": handle_transaction_updated,
        "transaction.ready": handle_transaction_ready,
        "subscription.activated": handle_subscription_activated,
        "transaction.completed": handle_transaction_completed,
        "payment_method.saved": handle_payment_method_saved,
        "address.created": handle_address_created,
        "subscription.canceled" : handle_subscription_canceled
    }

    handler = handler_map.get(event_type)
    if handler:
        await handler(payload, db)
    else:
        logger.warning(f"⚠️ No handler for event: {event_type}")

# -------------------- HANDLERS --------------------




def require_job_secret(request: Request):
    """
    Protects admin job endpoints. Set ADMIN_JOB_SECRET in env and pass it as header:
    X-Admin-Job: <secret>
    """
    expected = os.getenv("ADMIN_JOB_SECRET")
    provided = request.headers.get("x-admin-job")
    if not expected or provided != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")



async def handle_subscription_canceled(payload: dict, db):
    data = payload.get("data", {})
    sub_id = data.get("id")
    canceled_at = data.get("canceled_at")

    if not sub_id:
        logging.warning("⚠️ Skipping subscription cancellation: no ID in payload")
        return

    subscription = db.query(Subscription).filter_by(id=sub_id).first()
    if not subscription:
        logging.warning(f"⚠️ Subscription {sub_id} not found, cannot cancel")
        return

    subscription.status = "canceled"
    subscription.canceled_at = parse_datetime(canceled_at)
    subscription.updated_at = parse_datetime(data.get("updated_at"))

    db.commit()
    logging.info(f"✅ Subscription {sub_id} marked as canceled")







async def handle_customer_created(payload: dict, db):
    data = payload.get("data", {})
    customer_id = data.get("id")

    if not customer_id:
        logging.warning("⚠️ Skipping customer creation: no customer ID in payload")
        return

    existing = db.query(Customer).filter_by(id=customer_id).first()
    if existing:
        logging.info(f"✅ Customer {customer_id} already exists, skipping.")
        return

    customer = Customer(
        id=customer_id,
        email=data.get("email", "unknown@example.com"),
        name=data.get("name"),
        locale=data.get("locale"),
        status=data.get("status"),
        marketing_consent=str(data.get("marketing_consent")) if data.get("marketing_consent") is not None else None,
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at")),
    )

    db.add(customer)
    db.commit()
    logging.info(f"✅ Created customer {customer_id}")


async def handle_subscription_created(payload: dict, db):
    data = payload.get("data", {})
    sub_id = data.get("id")
    customer_id = data.get("customer_id")

    if not sub_id:
        logging.warning("⚠️ Skipping subscription: no ID in payload")
        return
    if not customer_id:
        logging.warning("⚠️ Skipping subscription: unknown customer ID None")
        return

    existing = db.query(Subscription).filter_by(id=sub_id).first()
    if existing:
        logging.info(f"✅ Subscription {sub_id} already exists, skipping.")
        return

    # ensure customer exists
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        logging.warning(f"⚠️ Skipping subscription: customer {customer_id} not found")
        return

    subscription = Subscription(
        id=sub_id,
        customer_id=customer_id,
        status=data.get("status", "unknown"),
        started_at=parse_datetime(data.get("started_at")),
        ended_at=parse_datetime(data.get("canceled_at")),  # may be None
        next_billed_at=parse_datetime(data.get("next_billed_at")),
        updated_at=parse_datetime(data.get("updated_at")),
        canceled_at=parse_datetime(data.get("canceled_at")),
    )

    db.add(subscription)
    db.commit()
    logging.info(f"✅ Created subscription {sub_id} for customer {customer_id}")


async def handle_transaction_paid(payload: dict, db):
    data = payload.get("data", {})
    txn_id = data.get("id")
    customer_id = data.get("customer_id")

    if not txn_id:
        logging.warning("⚠️ Skipping transaction: no ID in payload")
        return
    if not customer_id:
        logging.warning("⚠️ Skipping transaction: unknown customer ID")
        return

    existing = db.query(Transaction).filter_by(id=txn_id).first()
    if existing:
        logging.info(f"✅ Transaction {txn_id} already exists, skipping.")
        return

    # Ensure customer exists
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        logging.warning(f"⚠️ Skipping transaction: customer {customer_id} not found")
        return

    totals = data.get("details", {}).get("totals", {})
    amount = float(totals.get("total", 0)) / 100  # Convert cents to dollars

    transaction = Transaction(
        id=txn_id,
        customer_id=customer_id,
        status=data.get("status"),
        amount=amount,
        currency=totals.get("currency_code"),
        invoice_id=data.get("invoice_id"),
        invoice_number=data.get("invoice_number"),
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at")),
        paid_at=parse_datetime(data["payments"][0]["captured_at"]) if data.get("payments") else None,
        subscription_id=data.get("subscription_id"),
    )

    db.add(transaction)
    db.commit()
    logging.info(f"✅ Saved transaction {txn_id} for customer {customer_id}")







# -------------------- STUBS --------------------

async def handle_transaction_created(payload, db: Session):
    logger.info("📥 Received transaction.created")

async def handle_transaction_updated(payload, db: Session):
    logger.info("📥 Received transaction.updated")

async def handle_transaction_ready(payload, db: Session):
    logger.info("📥 Received transaction.ready")

async def handle_subscription_activated(payload, db: Session):
    logger.info("📥 Received subscription.activated")

async def handle_transaction_completed(payload, db: Session):
    logger.info("📥 Received transaction.completed")

async def handle_payment_method_saved(payload, db: Session):
    logger.info("📥 Received payment_method.saved")

async def handle_address_created(payload, db: Session):
    logger.info("📥 Received address.created")
