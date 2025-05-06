from pydantic import BaseModel
from sqlalchemy import Column, Integer, String
from database import Base
from sqlalchemy import Column, Integer, String, UniqueConstraint

class DeviceStatus(Base):
    __tablename__ = "device_status"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    last_seen = Column(Integer)


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
