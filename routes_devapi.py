# routes_devapi.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from starlette.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, text

from auth import get_db
from models import ApiKey, DeviceData, DeviceStatus
from sse_broker import broker

router = APIRouter()

# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────

def _unauth(detail="Missing API key."):
    raise HTTPException(status_code=401, detail=detail)

def read_devapi_key(request: Request) -> str:
    """
    Read API key from header (X-API-Key) or ?api_key= query param.
    """
    h = request.headers
    q = request.query_params
    key = (
        h.get("x-api-key")
        or h.get("X-API-Key")
        or h.get("X-Api-Key")
        or q.get("api_key")
    )
    if not key:
        _unauth()
    return key.strip()

def require_active_key(db: Session, api_key: str) -> ApiKey:
    row = db.query(ApiKey).filter(
        ApiKey.key == api_key,
        ApiKey.status == "active",
        ApiKey.revoked_at.is_(None)
    ).first()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")
    return row

def resolve_device_for_key(db: Session, keyrow: ApiKey, device_id: Optional[str]) -> str | None:
    """
    If key is bound → use bound device (ignore mismatched device_id).
    If unbound → require device_id and ensure it belongs to the user.
    """
    if keyrow.device_id:
        if device_id and str(device_id) != str(keyrow.device_id):
            raise HTTPException(status_code=403, detail=f"Key is bound to {keyrow.device_id}.")
        return str(keyrow.device_id)

    # Unbound key must specify a device owned by the user.
    if not device_id:
        return None

    owned = db.query(DeviceStatus).filter(
        DeviceStatus.user_id == keyrow.user_id,
        DeviceStatus.device_id == device_id
    ).first()
    if not owned:
        raise HTTPException(status_code=403, detail="device_id not found for this account.")
    return str(device_id)

def parse_time_to_epoch(s: Optional[str]) -> Optional[int]:
    """
    Accepts UNIX epoch string OR ISO-8601 (e.g., 2025-08-30T06:30:19Z).
    Returns epoch seconds (int) or None.
    """
    if not s:
        return None
    s = s.strip()
    # epoch?
    if s.isdigit():
        return int(s)
    # ISO 8601
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        return int(dt.timestamp())
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {s}")

# ───────────────────────────────────────────────────────────────────────────────
# Historical Telemetry (REST)
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/devapi/telemetry")
def devapi_telemetry(
    request: Request,
    db: Session = Depends(get_db),
    device_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO8601 or epoch"),
    until: Optional[str] = Query(None, description="ISO8601 or epoch"),
    limit: int = Query(100, ge=1, le=1000)
):
    """
    Return recent telemetry for the device bound to the key, or for ?device_id= when
    the key is unbound (and the device belongs to the key owner).

    Filters:
      - ?since= / ?until=  (ISO8601 '...Z' or epoch seconds)
      - ?limit=1..1000     (default 100)
    """
    api_key = read_devapi_key(request)
    keyrow  = require_active_key(db, api_key)
    target  = resolve_device_for_key(db, keyrow, device_id)

    if keyrow.device_id is None and target is None:
        # unbound key & no device_id provided
        raise HTTPException(status_code=400, detail="device_id is required for unbound keys.")

    epoch_since = parse_time_to_epoch(since)
    epoch_until = parse_time_to_epoch(until)

    q = (
        db.query(DeviceData, DeviceStatus.label.label("label"))
          .join(DeviceStatus, DeviceStatus.device_id == DeviceData.device_id)
          .filter(DeviceStatus.user_id == keyrow.user_id)
    )

    if target:
        q = q.filter(DeviceData.device_id == target)

    if epoch_since is not None:
        q = q.filter(DeviceData.timestamp >= epoch_since)
    if epoch_until is not None:
        q = q.filter(DeviceData.timestamp <= epoch_until)

    rows = (
        q.order_by(DeviceData.timestamp.desc())
         .limit(limit)
         .all()
    )

    def ser(dd: DeviceData, label: Optional[str]):
        return {
            "id": dd.id,
            "device_id": dd.device_id,
            "label": label,
            "data": dd.data,
            "timestamp": dd.timestamp,
            "ts_iso": datetime.fromtimestamp(dd.timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        }

    out = [ser(dd, lbl) for (dd, lbl) in rows]
    return JSONResponse(out)

# ───────────────────────────────────────────────────────────────────────────────
# Live Stream (SSE)
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/devapi/stream")
def devapi_stream(
    request: Request,
    db: Session = Depends(get_db),
    device_id: Optional[str] = Query(None),
):
    """
    SSE stream for a single device.
    - If the API key is bound → streams that device automatically.
    - If unbound → ?device_id= is required (must belong to the key's user).

    Events you already publish:
      broker.publish((user_id, device_id), payload, event="telemetry")
      broker.publish((user_id, device_id), payload, event="heartbeat")
    """
    api_key = read_devapi_key(request)
    keyrow  = require_active_key(db, api_key)
    target  = resolve_device_for_key(db, keyrow, device_id)

    if keyrow.device_id is None and target is None:
        raise HTTPException(status_code=400, detail="device_id is required for unbound keys.")

    topic = (int(keyrow.user_id), str(target or keyrow.device_id))

    async def gen() -> AsyncIterator[bytes]:
        # Make proxies happier + set auto-retry
        yield b": connected\nretry: 3000\n\n"

        async with broker.subscribe(topic) as stream:
            async for msg in stream:
                # normalize message -> (event_type, payload)
                if isinstance(msg, tuple) and len(msg) == 2:
                    event_type, payload = msg
                elif isinstance(msg, dict):
                    event_type = msg.get("event", "message")
                    payload    = msg.get("data", msg)
                else:
                    event_type, payload = "message", msg

                data_str = json.dumps(payload, ensure_ascii=False)
                yield f"event: {event_type}\n".encode("utf-8")
                yield f"data: {data_str}\n\n".encode("utf-8")

                if await request.is_disconnected():
                    break

        yield b": bye\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
