# devapi_auth.py
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import Optional, Tuple

from auth import get_db
from models import ApiKey, DeviceStatus  # ApiKey has: key, status, user_id, device_id, user relationship

APIKeyContext = Tuple[int, str, Optional[str]]
# -> (owner_user_id, device_id, device_label)

def _resolve_label(db: Session, user_id: int, device_id: str) -> Optional[str]:
    row = db.query(DeviceStatus.label).filter(
        DeviceStatus.user_id == user_id,
        DeviceStatus.device_id == device_id
    ).first()
    return row[0] if row else None

async def api_key_auth(
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, convert_underscores=False),
    x_device_id: Optional[str] = Header(None, convert_underscores=False),
    api_key_qs: Optional[str] = None,  # for SSE query param fallback
) -> APIKeyContext:
    # Accept header OR ?api_key=... for SSE (EventSource cannot set headers).
    key_value = x_api_key or api_key_qs
    if not key_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key.")

    api_key = db.query(ApiKey).filter(ApiKey.key == key_value, ApiKey.status == "active").first()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key.")

    if not api_key.device_id:
        raise HTTPException(status_code=403, detail="API key not yet bound to a device.")

    # Optional additional guard: if caller provided X-Device-Id, enforce it matches
    if x_device_id and x_device_id != api_key.device_id:
        raise HTTPException(status_code=403, detail=f"Key bound to a different device ({api_key.device_id}).")

    owner_user_id = int(api_key.user_id)
    device_id = str(api_key.device_id)
    label = _resolve_label(db, owner_user_id, device_id)
    return (owner_user_id, device_id, label)
