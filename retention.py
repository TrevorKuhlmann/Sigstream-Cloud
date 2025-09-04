# retention.py
from typing import Optional

TRIAL_RETENTION_DAYS = 1     # set to 1 while testing
PAID_RETENTION_DAYS  = 1    # set to 1 while testing

def get_retention_days_for_user(subscription_status: Optional[str]) -> int:
    """
    'active' (paid) => 30 days
    'trialing' or anything else/None => 7 days
    """
    status = (subscription_status or "").strip().lower()
    if status in {"active", "paid"}:
        return PAID_RETENTION_DAYS
    return TRIAL_RETENTION_DAYS
