# limits.py
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from models import ApiKey, User  # types only

# Tunables (you can move to ENV if you prefer)
TRIAL_MAX_KEYS = 3
PAID_MAX_KEYS  = 30

HAS_ACTIVE_SQL = text("SELECT has_active_subscription(:email)")

def max_keys_for_user(db: Session, email: str) -> int:
    """Return the allowed number of active keys for this user."""
    is_active = db.execute(HAS_ACTIVE_SQL, {"email": email}).scalar() == "ACTIVE"
    return PAID_MAX_KEYS if is_active else TRIAL_MAX_KEYS

def active_key_count(db: Session, user_id: int) -> int:
    """Count user's ACTIVE, non-revoked keys."""
    return (
        db.query(func.count(ApiKey.id))
          .filter(ApiKey.user_id == user_id,
                  ApiKey.status == "active",
                  ApiKey.revoked_at.is_(None))
          .scalar()
        or 0
    )
