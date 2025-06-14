from datetime import datetime
from typing import Optional

def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parses ISO8601 date strings to datetime or returns None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
