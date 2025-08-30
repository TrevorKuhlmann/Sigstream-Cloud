# routes_devapi.py
from fastapi import APIRouter, Request, Depends, Header, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from auth import get_db
from models import ApiKey, DeviceData, DeviceStatus

router = APIRouter()

# --- helpers ---------------------------------------------------------------

def _missing():
    raise HTTPException(status_code=401, detail="Missing API key.")

def read_devapi_key(
    request: Request,
    x_api_key: str | None = Header(default=None),              # normal FastAPI mapping -> x-api-key
    api_key_q: str | None = Query(default=None, alias="api_key")
) -> str:
    """
    Accept API key via header (any case) OR query string (?api_key=...).
    This avoids client/proxy header quirks.
    """
    key = (
        x_api_key
        or request.headers.get("x-api-key")
        or request.headers.get("X-API-Key")
        or request.headers.get("X-Api-Key")
        or api_key_q
    )
    if not key:
        _missing()
    return key.strip()

def device_scope_for_key(db: Session, keyrow: ApiKey) -> list[str]:
    """If key is bound -> just that device. Else -> all devices for the user."""
    if keyrow.device_id:
        return [keyrow.device_id]
    return [
        r.device_id
        for r in db.query(DeviceStatus.device_id)
                   .filter(DeviceStatus.user_id == keyrow.user_id)
                   .all()
        if r.device_id
    ]

def parse_since(since: str) -> int:
    """Return epoch seconds from ISO8601 or already-epoch string."""
    if since.isdigit():
        return int(since)
    # tolerate trailing Z
    return int(datetime.fromisoformat(since.replace("Z", "")).timestamp())

# --- REST: recent telemetry ------------------------------------------------

@router.get("/devapi/telemetry")
def devapi_telemetry(
    request: Request,
    limit: int = 100,
    since: str | None = None,
    db: Session = Depends(get_db),
):
    api_key = read_devapi_key(request)

    keyrow = (
        db.query(ApiKey)
          .filter(ApiKey.key == api_key, ApiKey.status == "active")
          .first()
    )
    if not keyrow:
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")

    device_ids = device_scope_for_key(db, keyrow)
    if not device_ids:
        return []

    q = db.query(DeviceData).filter(DeviceData.device_id.in_(device_ids))

    if since:
        try:
            cutoff = parse_since(since)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid 'since' value. Use epoch seconds or ISO8601 (e.g. 2025-08-30T12:34:56Z).")
        q = q.filter(DeviceData.timestamp >= cutoff)

    rows = q.order_by(DeviceData.timestamp.desc()).limit(min(limit, 1000)).all()

    # decorate with labels
    label_map = dict(
        db.query(DeviceStatus.device_id, DeviceStatus.label)
          .filter(DeviceStatus.device_id.in_(device_ids))
          .all()
    )

    return [
        {
            "id": r.id,
            "device_id": r.device_id,
            "label": label_map.get(r.device_id),
            "data": r.data,
            "timestamp": r.timestamp,
            "ts_iso": datetime.utcfromtimestamp(r.timestamp).isoformat() + "Z",
        }
        for r in rows
    ]
