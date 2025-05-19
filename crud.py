from database import SessionLocal
from models import DeviceData
from models import DeviceStatus
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session
from models import DeviceData, DeviceStatus, User

def insert_data(
    device_id: str,
    data: str,
    timestamp: int,
    db: Session,
    user: User
):
    """
    Insert a new data record and ensure there is a DeviceStatus
    row for this device owned by the given user.
    """
    # Try to find an existing status for this user
    status = (
        db.query(DeviceStatus)
          .filter(
              DeviceStatus.device_id == device_id,
              DeviceStatus.user_id == user.id
          )
          .first()
    )
    if not status:
        # Create & claim the device
        status = DeviceStatus(
            device_id=device_id,
            last_seen=timestamp,
            user_id=user.id
        )
        db.add(status)
        db.commit()

    # Insert the telemetry record
    record = DeviceData(
        device_id=device_id,
        data=data,
        timestamp=timestamp
    )
    db.add(record)
    db.commit()


def update_heartbeat(
    device_id: str,
    timestamp: int,
    db: Session,
    user: User
):
    """
    Update the last_seen timestamp for a claimed device;
    if it doesn’t exist yet, create & claim it.
    """
    status = (
        db.query(DeviceStatus)
          .filter(
              DeviceStatus.device_id == device_id,
              DeviceStatus.user_id == user.id
          )
          .first()
    )
    if status:
        status.last_seen = timestamp
    else:
        status = DeviceStatus(
            device_id=device_id,
            last_seen=timestamp,
            user_id=user.id
        )
        db.add(status)
    db.commit()
