import logging
from sqlalchemy.orm import Session
from models import Customer, Subscription, Transaction, PaymentMethod, Address
from .utils import parse_datetime

logger = logging.getLogger(__name__)

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
    }

    handler = handler_map.get(event_type)
    if handler:
        await handler(payload, db)
    else:
        logger.warning(f"⚠️ No handler for event: {event_type}")

# -------------------- HANDLERS --------------------

async def handle_customer_created(payload, db: Session):
    customer_id = payload.get("id")
    if not customer_id:
        logger.warning("⚠️ Skipping customer creation: no customer ID in payload")
        return

    existing = db.query(Customer).filter_by(id=customer_id).first()
    if existing:
        logger.info(f"✅ Customer already exists: {customer_id}")
        return

    obj = Customer(
        id=customer_id,
        email=payload.get("email") or "unknown@example.com",
        name=payload.get("name"),
        created_at=parse_datetime(payload.get("created_at")),
        updated_at=parse_datetime(payload.get("updated_at")),
        locale=payload.get("locale"),
        marketing_consent=payload.get("marketing_consent"),
        status=payload.get("status"),
        country_code=payload.get("country_code"),
    )
    db.add(obj)
    db.commit()
    logger.info(f"✅ Created customer: {customer_id}")

async def handle_subscription_created(payload, db: Session):
    sub_id = payload.get("id")
    customer_id = payload.get("customer_id")

    existing = db.query(Subscription).filter_by(id=sub_id).first()
    if existing:
        logger.info(f"✅ Subscription already exists: {sub_id}")
        return

    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        logger.warning(f"⚠️ Skipping subscription: unknown customer ID {customer_id}")
        return

    sub = Subscription(
        id=sub_id,
        customer_id=customer_id,
        status=payload.get("status"),
        started_at=parse_datetime(payload.get("started_at")),
        ended_at=parse_datetime(payload.get("ended_at")),
        next_billed_at=parse_datetime(payload.get("next_billed_at")),
        updated_at=parse_datetime(payload.get("updated_at")),
        canceled_at=parse_datetime(payload.get("canceled_at")),
    )
    db.add(sub)
    db.commit()
    logger.info(f"✅ Created subscription: {sub_id}")

async def handle_transaction_paid(payload, db: Session):
    tx_id = payload.get("id")
    customer_id = payload.get("customer_id")

    if not tx_id:
        logger.warning("⚠️ Skipping transaction: no ID in payload")
        return

    existing = db.query(Transaction).filter_by(id=tx_id).first()
    if existing:
        logger.info(f"✅ Transaction already exists: {tx_id}")
        return

    tx = Transaction(
        id=tx_id,
        customer_id=customer_id,
        status=payload.get("status"),
        amount=payload.get("amount"),
        currency=payload.get("currency_code"),
        invoice_id=payload.get("invoice_id"),
        invoice_number=payload.get("invoice_number"),
        created_at=parse_datetime(payload.get("created_at")),
        updated_at=parse_datetime(payload.get("updated_at")),
        paid_at=parse_datetime(payload.get("paid_at")),
        subscription_id=payload.get("subscription_id"),
        # tax_rate is ignored unless you add it to the model
    )
    db.add(tx)
    db.commit()
    logger.info(f"✅ Recorded transaction: {tx_id}")

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
