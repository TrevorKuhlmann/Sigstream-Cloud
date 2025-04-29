from database import SessionLocal, init_db
from models import DeviceData

init_db()

def insert_data(device_id: str, data: str, timestamp: int):
    db = SessionLocal()
    record = DeviceData(device_id=device_id, data=data, timestamp=timestamp)
    db.add(record)
    db.commit()
    db.close()
