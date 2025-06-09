from fastapi import Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
import logging
from database import get_db
import models

def parse_datetime(dt):
    return datetime.fromisoformat(dt.replace("Z", "+00:00")) if dt else None

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

# Handlers

# async def handle_customer_created(payload: dict, db: Session):
#     data = payload["data"]
#     customer = db.query(models.Customer).get(data["id"])
#     if not customer:
#         customer = models.Customer(
#             id=data["id"],
#             email=data["email"],
#             name=data.get("name"),
#             locale=data.get("locale"),
#             status=data.get("status"),
#             created_at=parse_datetime(data.get("created_at")),
#             updated_at=parse_datetime(data.get("updated_at"))
#         )
#         db.add(customer)
#     else:
#         customer.email = data["email"]
#         customer.name = data.get("name")
#         customer.locale = data.get("locale")
#         customer.status = data.get("status")
#         customer.updated_at = parse_datetime(data.get("updated_at"))
#     db.commit()

async def handle_transaction_created(payload: dict, db: Session):
    data = payload["data"]
    customer_id = data.get("customer_id")

    # 💡 Ensure the customer exists
    if customer_id:
        existing_customer = db.query(models.Customer).get(customer_id)
        if not existing_customer:
            logging.warning(f"Customer {customer_id} not found. Creating placeholder.")
            placeholder = models.Customer(
                id=customer_id,
                email=None,
                name=None,
                locale=None,
                status="unknown"
            )
            db.add(placeholder)
            db.commit()

    txn = models.Transaction(
        id=data["id"],
        status=data.get("status"),
        customer_id=customer_id,
        amount=data["details"]["totals"]["total"],
        currency=data.get("currency_code"),
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at"))
    )
    db.add(txn)
    db.commit()


async def handle_address_created(payload: dict, db: Session):
    data = payload["data"]
    address = models.Address(
        id=data["id"],
        customer_id=data["customer_id"],
        country_code=data["country_code"],
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at"))
    )
    db.add(address)
    db.commit()

async def handle_transaction_created(payload: dict, db: Session):
    data = payload["data"]
    txn = models.Transaction(
        id=data["id"],
        status=data.get("status"),
        customer_id=data.get("customer_id"),
        amount=data["details"]["totals"]["total"],
        currency=data.get("currency_code"),
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at"))
    )
    db.add(txn)
    db.commit()

async def handle_transaction_updated(payload: dict, db: Session):
    await handle_transaction_created(payload, db)

async def handle_transaction_ready(payload: dict, db: Session):
    await handle_transaction_created(payload, db)

async def handle_transaction_paid(payload: dict, db: Session):
    data = payload["data"]
    txn = db.query(models.Transaction).get(data["id"])
    if txn:
        txn.status = "paid"
        txn.updated_at = parse_datetime(data.get("updated_at"))
        txn.paid_at = parse_datetime(data.get("billed_at"))
        db.commit()

async def handle_transaction_completed(payload: dict, db: Session):
    data = payload["data"]
    txn = db.query(models.Transaction).get(data["id"])
    if txn:
        txn.status = "completed"
        txn.updated_at = parse_datetime(data.get("updated_at"))
        txn.invoice_id = data.get("invoice_id")
        txn.invoice_number = data.get("invoice_number")
        db.commit()

async def handle_payment_method_saved(payload: dict, db: Session):
    data = payload["data"]
    method = models.PaymentMethod(
        id=data["id"],
        customer_id=data["customer_id"],
        type=data["type"],
        address_id=data.get("address_id"),
        updated_at=parse_datetime(data.get("updated_at"))
    )
    db.add(method)
    db.commit()

async def handle_subscription_created(payload: dict, db: Session):
    data = payload["data"]
    sub = models.Subscription(
        id=data["id"],
        customer_id=data["customer_id"],
        status=data["status"],
        started_at=parse_datetime(data.get("started_at")),
        next_billed_at=parse_datetime(data.get("next_billed_at")),
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at")),
        collection_mode=data.get("collection_mode"),
        currency_code=data.get("currency_code")
    )
    db.add(sub)
    db.commit()

async def handle_subscription_activated(payload: dict, db: Session):
    await handle_subscription_created(payload, db)

event_handlers = {
    "customer.created": handle_customer_created,
    "address.created": handle_address_created,
    "transaction.created": handle_transaction_created,
    "transaction.updated": handle_transaction_updated,
    "transaction.ready": handle_transaction_ready,
    "transaction.paid": handle_transaction_paid,
    "transaction.completed": handle_transaction_completed,
    "payment_method.saved": handle_payment_method_saved,
    "subscription.created": handle_subscription_created,
    "subscription.activated": handle_subscription_activated,
}
