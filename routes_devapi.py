# routes_devapi.py
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session

from auth import get_db
from models import DeviceData
from devapi_auth import api_key_auth, APIKeyContext
from sse_broker import broker

router = APIRouter(prefix="/devapi", tags=["Developer API"])

def row_to_dict(row: DeviceData, label: Optional[str]) -> Dict[str, Any]:
    # Your DeviceData fields (from main.py usage): id, device_id, data, timestamp (epoch int)
    return {
        "id": row.id,
        "device_id": row.device_id,
        "label": label,
        "data": row.data,
        "timestamp": row.timestamp,               # epoch seconds
        "ts_iso": datetime.utcfromtimestamp(row.timestamp).isoformat() + "Z",
    }

@router.get("/telemetry")
def list_telemetry(
    ctx: APIKeyContext = Depends(api_key_auth),
    db: Session = Depends(get_db),
    since: Optional[datetime] = Query(None, description="ISO8601; return rows >= this timestamp"),
    limit: int = Query(200, ge=1, le=2000),
):
    owner_user_id, device_id, label = ctx
    q = db.query(DeviceData).filter(
        DeviceData.user_id == owner_user_id,
        DeviceData.device_id == device_id
    )
    if since:
        q = q.filter(DeviceData.timestamp >= int(since.timestamp()))
    rows: List[DeviceData] = q.order_by(DeviceData.timestamp.desc()).limit(limit).all()
    return JSONResponse([row_to_dict(r, label) for r in rows])

@router.get("/stream")
async def stream_telemetry(
    request: Request,
    ctx: APIKeyContext = Depends(api_key_auth),
    api_key: Optional[str] = Query(None, alias="api_key"),  # enables ?api_key=... for EventSource
):
    owner_user_id, device_id, label = ctx

    async def gen():
        q = await broker.subscribe((owner_user_id, device_id))
        try:
            # hello
            yield (
                "event: hello\n"
                f'data: {{"device_id":"{device_id}","label":{("null" if label is None else f"{repr(label)}")}}}\n\n'
            )

            async def keepalives():
                try:
                    while True:
                        await asyncio.sleep(20)
                        await broker.keepalive((owner_user_id, device_id))
                except asyncio.CancelledError:
                    pass
            task = asyncio.create_task(keepalives())

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": idle\n\n"
        finally:
            await broker.unsubscribe((owner_user_id, device_id), q)
            task.cancel()

    headers = {
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
