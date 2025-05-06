from database import SessionLocal, init_db
from models import DeviceData
from models import DeviceStatus
from sqlalchemy.exc import NoResultFound

init_db()

def update_heartbeat(device_id: str, timestamp: int):
    db = SessionLocal()
    try:
        status = db.query(DeviceStatus).filter(DeviceStatus.device_id == device_id).one()
        status.last_seen = timestamp
    except NoResultFound:
        status = DeviceStatus(device_id=device_id, last_seen=timestamp)
        db.add(status)
    db.commit()
    db.close()




def insert_data(device_id: str, data: str, timestamp: int):
    db = SessionLocal()
    record = DeviceData(device_id=device_id, data=data, timestamp=timestamp)
    db.add(record)
    db.commit()
    db.close()
