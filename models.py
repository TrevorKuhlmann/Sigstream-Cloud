from pydantic import BaseModel
from sqlalchemy import Column, Integer, String
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
