# purge.py
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import delete
from models import DeviceData, User
from retention import get_retention_days_for_user

def purge_old_device_data(db: Session) -> int:
    """
    Per-tenant purge using each user's retention window.
    DeviceData.timestamp is epoch seconds (int), so we compare against epoch cutoff.
    Returns total number of rows deleted.
    """
    total_deleted = 0
    now = datetime.now(timezone.utc)

    for user in db.query(User).all():
        days = get_retention_days_for_user(user.subscription_status)
        cutoff_epoch = int((now - timedelta(days=days)).timestamp())

        # Delete only this user's rows older than cutoff
        stmt = (
            delete(DeviceData)
            .where(DeviceData.user_id == user.id)
            .where(DeviceData.timestamp < cutoff_epoch)
        )
        res = db.execute(stmt)
        total_deleted += res.rowcount or 0

    db.commit()
    return total_deleted
