from pydantic import BaseModel
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from database import Base

from sqlalchemy import Boolean, DateTime


from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from database import Base

# -------------------- Device and User Models --------------------

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

    # Email confirmation fields
    email_confirmed    = Column(Boolean, default=False, nullable=False)
    email_confirmed_at = Column(DateTime, nullable=True)

    devices = relationship("DeviceStatus", back_populates="owner")
    api_keys = relationship("ApiKey", back_populates="user")

class DeviceStatus(Base):
    __tablename__ = 'device_status'

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    last_seen = Column(Integer)
    user_id = Column(Integer, ForeignKey("users.id"))
    label = Column(String)

    owner = relationship("User", back_populates="devices")

# -------------------- Paddle Webhook Models --------------------

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True)  # Paddle Customer ID
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    locale = Column(String, nullable=True)
    marketing_consent = Column(String, nullable=True)
    status = Column(String, nullable=True)
    country_code = Column(String, nullable=True)  # ← Add this if used in handler

    subscriptions = relationship("Subscription", back_populates="customer")
    transactions = relationship("Transaction", back_populates="customer")
    payment_methods = relationship("PaymentMethod", back_populates="customer")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True)  # Paddle Subscription ID
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    status = Column(String, nullable=False)              # 'active', 'canceled', etc.
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    next_billed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="subscriptions")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True)  # Paddle Transaction ID
    customer_id = Column(String, ForeignKey("customers.id"))
    status = Column(String)
    amount = Column(Float)
    currency = Column(String)
    invoice_id = Column(String)
    invoice_number = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    paid_at = Column(DateTime)
    subscription_id = Column(String, ForeignKey("subscriptions.id"), nullable=True)  # ← Add this
    customer = relationship("Customer", back_populates="transactions")

class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    type = Column(String)
    brand = Column(String)
    last4 = Column(String)
    exp_month = Column(Integer)
    exp_year = Column(Integer)
    updated_at = Column(DateTime)

    customer = relationship("Customer", back_populates="payment_methods")

class Address(Base):
    __tablename__ = "addresses"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    country_code = Column(String)
    region = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


    #--

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)   # ✅ Must have primary_key=True
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    key = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default="active")
    created_at = Column(DateTime, server_default=func.now())
    revoked_at = Column(DateTime, nullable=True)
    device_id = Column(String, nullable=True)
    bound_at = Column(DateTime, nullable=True)   # ✅ Your new audit column

    user = relationship("User", back_populates="api_keys")
