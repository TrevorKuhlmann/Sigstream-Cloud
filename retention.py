# retention.py
from typing import Optional

# Single-product funnel:
TRIAL_RETENTION_DAYS = 7
PAID_RETENTION_DAYS  = 30

def get_retention_days_for_user(subscription_status: Optional[str]) -> int:
    """
    Returns retention days for a given user status.
    'active' => paid (30d), everything else => trial (7d).
    You can refine the mapping later if you add more states.
    """
    status = (subscription_status or "").strip().lower()
    if status in {"active"}:
        return PAID_RETENTION_DAYS
    # treat trialing / none / canceled / past_due as trial window for now
    return TRIAL_RETENTION_DAYS
