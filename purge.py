# purge.py
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, text
from sqlalchemy.orm import Session
from models import DeviceData, User
from retention import get_retention_days_for_user

TRIALING_EXISTS_SQL = text("""
SELECT EXISTS (
    SELECT 1
    FROM public.customers c
    JOIN public.subscriptions s ON s.customer_id = c.id
    WHERE upper(c.email) = upper(:email)
      AND s.status = 'trialing'
      AND (s.canceled_at IS NULL OR s.canceled_at > NOW())
)
""")

HAS_ACTIVE_SQL = text("SELECT has_active_subscription(:email)")

def purge_old_device_data(db: Session) -> int:
    """
    Per-user purge using your 'has_active_subscription' function to detect
    active vs not-active, then a small EXISTS check to treat 'trialing' as trial.
    """
    total_deleted = 0
    now = datetime.now(timezone.utc)

    # Loop through users (only need id + email)
    for user_id, email in db.query(User.id, User.email).all():
        # 1) use your function
        fn = db.execute(HAS_ACTIVE_SQL, {"email": email}).scalar()
        # 2) refine: if ACTIVE, decide 'trialing' vs 'active'
        if fn == "ACTIVE":
            is_trialing = db.execute(TRIALING_EXISTS_SQL, {"email": email}).scalar()
            sub_status = "trialing" if is_trialing else "active"
        else:
            sub_status = None  # treat as trial/none

        days = get_retention_days_for_user(sub_status)
        cutoff_epoch = int((now - timedelta(days=days)).timestamp())

        stmt = (
            delete(DeviceData)
            .where(DeviceData.user_id == user_id)
            .where(DeviceData.timestamp < cutoff_epoch)   # epoch int column
        )
        res = db.execute(stmt)
        total_deleted += res.rowcount or 0

    db.commit()
    return total_deleted
