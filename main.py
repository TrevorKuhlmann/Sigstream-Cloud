# routes_devapi.py
from __future__ import annotations

import json, time
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import anyio
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from starlette.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text

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
    Read API key from header or query. Supported:
      - X-API-Key (any casing)
      - ?api_key= or ?key=
    """
    h = request.headers
    q = request.query_params
    key = (
        h.get("x-api-key")
        or h.get("X-API-Key")
        or h.get("X-Api-Key")
        or q.get("api_key")
        or q.get("key")
    )
    if not key:
        _unauth()
    return str(key).strip()

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

def require_subscription_ok_for_key(db: Session, api_key: str) -> None:
    """
    Determine subscription status via the API key using your join chain.
    Allows 'active' or 'trialling'/'trialing' (cover both spellings).
    """
    sql = text("""
        SELECT 1
          FROM public.api_keys ky
          JOIN public.users us
            ON us.id = ky.user_id
          JOIN public.customers cst
            ON cst.email = us.email
          JOIN public.subscriptions subs
            ON subs.customer_id = cst.id
         WHERE ky.key = :key
           AND ky.status = 'active'
           AND subs.status IN ('active','trialling','trialing')
         LIMIT 1
    """)
    ok = db.execute(sql, {"key": api_key}).scalar()
    if not ok:
        raise HTTPException(
            status_code=403,
            detail="Subscription inactive. Please subscribe to access telemetry."
        )

def require_bound_device_id(db: Session, keyrow: ApiKey) -> str:
    """
    Enforce: key MUST be bound to a device AND that device must be registered
    for the same user. Otherwise 403/404.
    """
    if not keyrow.device_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a device.")
    device_id = str(keyrow.device_id)

    registered = (
        db.query(DeviceStatus.device_id)
          .filter(DeviceStatus.user_id == keyrow.user_id,
                  DeviceStatus.device_id == device_id)
          .scalar()
    )
    if not registered:
        raise HTTPException(status_code=404, detail="Device not registered.")
    return device_id

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
# Historical Telemetry (REST) — bound device + subscription check via API key
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/devapi/telemetry")
def devapi_telemetry(
    request: Request,
    db: Session = Depends(get_db),
    # kept but ignored to avoid breaking any existing callers; bound key controls the device
    device_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO8601 or epoch"),
    until: Optional[str] = Query(None, description="ISO8601 or epoch"),
    limit: int = Query(100, ge=1, le=1000)
):
    """
    Return recent telemetry ONLY for the device the API key is bound to.
    - Unbound keys → 403
    - Users without ACTIVE/TRIALLING/TRIALING subscription → 403
    """
    api_key = read_devapi_key(request)
    keyrow  = require_active_key(db, api_key)
    require_subscription_ok_for_key(db, api_key)
    target  = require_bound_device_id(db, keyrow)

    epoch_since = parse_time_to_epoch(since)
    epoch_until = parse_time_to_epoch(until)

    q = (
        db.query(DeviceData, DeviceStatus.label.label("label"))
          .join(DeviceStatus, DeviceStatus.device_id == DeviceData.device_id)
          .filter(DeviceStatus.user_id == keyrow.user_id,
                  DeviceData.device_id == target)
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
# Live Stream (SSE) — bound device + subscription check via API key
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/devapi/stream")
def devapi_stream(
    request: Request,
    db: Session = Depends(get_db),
    # kept but ignored; bound key controls the device
    device_id: Optional[str] = Query(None),
):
    """
    SSE stream ONLY for the device this API key is bound to.
    - Unbound keys → 403
    - Users without ACTIVE/TRIALLING/TRIALING subscription → 403
    """
    api_key = read_devapi_key(request)
    keyrow  = require_active_key(db, api_key)
    require_subscription_ok_for_key(db, api_key)
    target  = require_bound_device_id(db, keyrow)

    topic = (int(keyrow.user_id), str(target))

    async def gen() -> AsyncIterator[bytes]:
        # Start line + client retry hint
        yield b": connected\nretry: 3000\n\n"

        # Prefer queue-style subscribe (q.get). Fallback to async-iterable context manager.
        q = None
        try:
            q = await broker.subscribe(topic)  # queue-like in many implementations
        except TypeError:
            q = None
        except Exception:
            q = None

        if q is not None and hasattr(q, "get"):
            try:
                while True:
                    # heartbeat every 15s if no data
                    with anyio.move_on_after(15) as scope:
                        msg = await q.get()

                    if await request.is_disconnected():
                        break

                    if scope.cancel_called:
                        yield f": ping {int(time.time())}\n\n".encode("utf-8")
                        continue

                    # normalize message -> (event_type, payload)
                    event_type = "message"
                    payload = msg
                    if isinstance(msg, tuple) and len(msg) == 2:
                        event_type, payload = msg
                    elif isinstance(msg, dict):
                        event_type = msg.get("event") or "message"
                        payload = msg.get("data", msg)

                    yield f"event: {event_type}\n".encode("utf-8")
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
            finally:
                try:
                    await broker.unsubscribe(topic, q)
                except Exception:
                    pass
        else:
            # Fallback path: context manager / async-iterable style
            try:
                async with broker.subscribe(topic) as stream:
                    async for msg in stream:
                        if await request.is_disconnected():
                            break
                        event_type = "message"
                        payload = msg
                        if isinstance(msg, tuple) and len(msg) == 2:
                            event_type, payload = msg
                        elif isinstance(msg, dict):
                            event_type = msg.get("event") or "message"
                            payload = msg.get("data", msg)
                        yield f"event: {event_type}\n".encode("utf-8")
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
                        # optional lightweight ping
                        yield f": ping {int(time.time())}\n\n".encode("utf-8")
            except Exception:
                # Last-resort: keep socket open with pings
                while not await request.is_disconnected():
                    yield f": ping {int(time.time())}\n\n".encode("utf-8")
                    await anyio.sleep(15)

        yield b": bye\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
