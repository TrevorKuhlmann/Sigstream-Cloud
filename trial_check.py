from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User

TRIAL_DURATION_DAYS = 14

def is_in_trial(user: User) -> bool:
    """Check if the user is within their trial period."""
    if not user or not user.created_at:
        return False

    trial_expiry = user.created_at + timedelta(days=TRIAL_DURATION_DAYS)
    return datetime.utcnow() <= trial_expiry
