# routes_devapi.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from starlette.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

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
    Read API key from header or query param.
    Headers: X-API-Key / X-Api-Key
    Query:   ?key=...  or ?api_key=...
    """
    h = request.headers
    q = request.query_params
    key = (
        h.get("x-api-key")
        or h.get("X-API-Key")
        or h.get("X-Api-Key")
        or q.get("key")
        or q.get("api_key")
    )
    if not key:
        _unauth()
    return key.strip()

def require_active_key(db: Session, api_key: str) -> ApiKey:
    row = (
        db.query(ApiKey)
          .filter(
              ApiKey.key == api_key,
              ApiKey.status == "active",
              ApiKey.revoked_at.is_(None)
          )
          .first()
    )
    if not row:
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")
    return row

def require_bound_device_id(keyrow: ApiKey) -> str:
    """
    Enforce stricter policy: the key MUST be bound to a device.
    No access with unbound keys.
    """
    if not keyrow.device_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a device.")
    return str(keyrow.device_id)

def parse_time_to_epoch(s: Optional[str]) -> Optional[int]:
    """
    Accepts UNIX epoch string OR ISO-8601 (e.g., 2025-08-30T06:30:19Z).
    Returns epoch seconds (int) or None.
    """
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        return int(dt.timestamp())
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {s}")

# ───────────────────────────────────────────────────────────────────────────────
# Historical Telemetry (REST) — bound device only
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/devapi/telemetry")
def devapi_telemetry(
    request: Request,
    db: Session = Depends(get_db),
    since: Optional[str] = Query(None, description="ISO8601 or epoch"),
    until: Optional[str] = Query(None, description="ISO8601 or epoch"),
    limit: int = Query(100, ge=1, le=1000),
):
    """
    Returns recent telemetry ONLY for the device this API key is bound to.
    Unbound keys are rejected (403).
    Filters:
      - ?since= / ?until=  (ISO8601 '...Z' or epoch seconds)
      - ?limit=1..1000     (default 100)
    """
    api_key = read_devapi_key(request)
    keyrow  = require_active_key(db, api_key)
    device_id = require_bound_device_id(keyrow)  # enforce bound-only

    # Ensure the device is registered for this user
    registered = (
        db.query(DeviceStatus.device_id)
          .filter(
              DeviceStatus.user_id == keyrow.user_id,
              DeviceStatus.device_id == device_id
          )
          .scalar()
    )
    if not registered:
        raise HTTPException(status_code=404, detail="Device not registered.")

    epoch_since = parse_time_to_epoch(since)
    epoch_until = parse_time_to_epoch(until)

    q = (
        db.query(DeviceData, DeviceStatus.label.label("label"))
          .join(DeviceStatus, DeviceStatus.device_id == DeviceData.device_id)
          .filter(
              DeviceStatus.user_id == keyrow.user_id,
              DeviceData.device_id == device_id
          )
    )
    if epoch_since is not None:
        q = q.filter(DeviceData.timestamp >= epoch_since)
    if epoch_until is not None:
        q = q.filter(DeviceData.timestamp <= epoch_until)

    rows = q.order_by(DeviceData.timestamp.desc()).limit(limit).all()

    def ser(dd: DeviceData, label: Optional[str]):
        return {
            "id": dd.id,
            "device_id": dd.device_id,
            "label": label,
            "data": dd.data,
            "timestamp": dd.timestamp,
            "ts_iso": datetime.fromtimestamp(dd.timestamp, tz=timezone.utc)
                              .isoformat().replace("+00:00", "Z")
        }

    return JSONResponse([ser(dd, lbl) for (dd, lbl) in rows])

# ───────────────────────────────────────────────────────────────────────────────
# Live Stream (SSE) — bound device only
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/devapi/stream")
def devapi_stream(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    SSE stream for the single device bound to this API key.
    Unbound keys are rejected (403).

    Events you publish elsewhere:
      broker.publish((user_id, device_id), payload, event="telemetry")
      broker.publish((user_id, device_id), payload, event="heartbeat")
    """
    api_key = read_devapi_key(request)
    keyrow  = require_active_key(db, api_key)
    device_id = require_bound_device_id(keyrow)  # enforce bound-only

    # sanity: device registered for this user
    registered = (
        db.query(DeviceStatus.device_id)
          .filter(
              DeviceStatus.user_id == keyrow.user_id,
              DeviceStatus.device_id == device_id
          )
          .scalar()
    )
    if not registered:
        raise HTTPException(status_code=404, detail="Device not registered.")

    topic = (int(keyrow.user_id), device_id)

    async def gen() -> AsyncIterator[bytes]:
        # Helpful preamble for proxies + auto-retry
        yield b": connected\nretry: 3000\n\n"

        async with broker.subscribe(topic) as stream:
            async for msg in stream:
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
