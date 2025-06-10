from pydantic import BaseModel
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Float, DateTime
)
from sqlalchemy.orm import relationship
from database import Base

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

# -------------------- Existing Models --------------------

class DeviceDataIn(BaseModel):
    device_id: str
    data: str
    timestamp: int | None = None

class DeviceData(Base):
    __tablename__ = "device_data"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String)
    data = Column(String)
    timestamp = Column(Integer)

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    customer_name = Column(String)

    subscription_id = Column(String, nullable=True)
    plan_type = Column(String, nullable=True)
    subscription_status = Column(String, nullable=True)

    devices = relationship("DeviceStatus", back_populates="owner")

class DeviceStatus(Base):
    __tablename__ = 'device_status'

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    last_seen = Column(Integer)
    user_id = Column(Integer, ForeignKey("users.id"))
    label = Column(String)

    owner = relationship("User", back_populates="devices")

# -------------------- Paddle Webhook Models --------------------

# class Customer(Base):
#     __tablename__ = "customers"

#     id = Column(String, primary_key=True)
#     email = Column(String, nullable=False)
#     name = Column(String)
#     locale = Column(String)
#     status = Column(String)
#     created_at = Column(DateTime)
#     updated_at = Column(DateTime)

# class Address(Base):
#     __tablename__ = "addresses"

#     id = Column(String, primary_key=True)
#     customer_id = Column(String, ForeignKey("customers.id"))
#     country_code = Column(String)
#     created_at = Column(DateTime)
#     updated_at = Column(DateTime)

# class Transaction(Base):
#     __tablename__ = "transactions"

#     id = Column(String, primary_key=True)
#     customer_id = Column(String, ForeignKey("customers.id"))
#     status = Column(String)
#     amount = Column(Float)
#     currency = Column(String)
#     invoice_id = Column(String)
#     invoice_number = Column(String)
#     created_at = Column(DateTime)
#     updated_at = Column(DateTime)
#     paid_at = Column(DateTime)

# class PaymentMethod(Base):
#     __tablename__ = "payment_methods"

#     id = Column(String, primary_key=True)
#     customer_id = Column(String, ForeignKey("customers.id"))
#     type = Column(String)
#     address_id = Column(String, ForeignKey("addresses.id"))
#     updated_at = Column(DateTime)

# class Subscription(Base):
#     __tablename__ = "subscriptions"

#     id = Column(String, primary_key=True)
#     customer_id = Column(String, ForeignKey("customers.id"))
#     status = Column(String)
#     started_at = Column(DateTime)
#     next_billed_at = Column(DateTime)
#     created_at = Column(DateTime)
#     updated_at = Column(DateTime)
#     collection_mode = Column(String)
#     currency_code = Column(String)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True)  # Paddle customer ID
    email = Column(String, nullable=False)
    subscriptions = relationship("Subscription", back_populates="customer")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    status = Column(String, nullable=False)              # e.g. 'active', 'canceled', 'expired'
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    next_billed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="subscriptions")
