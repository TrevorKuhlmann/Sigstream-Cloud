from pydantic import BaseModel
from sqlalchemy import Column, Integer, String
from database import Base
from sqlalchemy import Column, Integer, String, UniqueConstraint


from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base





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
    label = Column(String)  # ✅ Make sure this is here

    owner = relationship("User", back_populates="devices")