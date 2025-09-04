from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models import DeviceData, DeviceStatus, User


def _ensure_device_status(db: Session, device_id: str, user_id: int, last_seen: int) -> DeviceStatus:
    """
    Get-or-create DeviceStatus(user_id, device_id). Updates last_seen if newer.
    Race-safe with a UNIQUE index on (user_id, device_id).
    """
    status = (
        db.query(DeviceStatus)
          .filter(DeviceStatus.device_id == device_id,
                  DeviceStatus.user_id == user_id)
          .first()
    )
    if status:
        if last_seen and (status.last_seen is None or last_seen > status.last_seen):
            status.last_seen = last_seen
        return status

    # Create (may collide under concurrent inserts -> handle via IntegrityError)
    status = DeviceStatus(device_id=device_id, user_id=user_id, last_seen=last_seen)
    db.add(status)
    try:
        db.flush()  # attempt insert without committing the whole txn yet
    except IntegrityError:
        db.rollback()  # someone else inserted it; re-fetch
        status = (
            db.query(DeviceStatus)
              .filter(DeviceStatus.device_id == device_id,
                      DeviceStatus.user_id == user_id)
              .first()
        )
        if status and last_seen and (status.last_seen is None or last_seen > status.last_seen):
            status.last_seen = last_seen
    return status


def insert_data(
    device_id: str,
    data: str,
    timestamp: int,
    db: Session,
    user: User
):
    """
    Insert telemetry and guarantee user ownership is attached.
    - Ensures DeviceStatus(user_id, device_id)
    - Inserts DeviceData with user_id populated
    - Single commit
    """
    _ensure_device_status(db, device_id, user.id, timestamp)

    record = DeviceData(
        device_id=device_id,
        data=data,
        timestamp=int(timestamp),
        user_id=user.id,          # ✅ critical: always set user_id
    )
    db.add(record)
    db.commit()
    return record


def update_heartbeat(
    device_id: str,
    timestamp: int,
    db: Session,
    user: User
):
    """
    Update last_seen; creates DeviceStatus if missing.
    """
    _ensure_device_status(db, device_id, user.id, int(timestamp))
    db.commit()
