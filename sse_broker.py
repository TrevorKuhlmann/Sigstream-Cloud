# sse_broker.py
import asyncio, json, time
from typing import Dict, Set, Tuple

Key = Tuple[int, str]  # (user_id, device_id)

class SSEBroker:
    def __init__(self):
        self.channels: Dict[Key, Set[asyncio.Queue]] = {}
        self.lock = asyncio.Lock()

    async def subscribe(self, key: Key) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self.lock:
            self.channels.setdefault(key, set()).add(q)
        return q

    async def unsubscribe(self, key: Key, q: asyncio.Queue):
        async with self.lock:
            qs = self.channels.get(key)
            if qs and q in qs:
                qs.remove(q)
                if not qs:
                    self.channels.pop(key, None)

    async def publish(self, key: Key, payload: dict, event: str = "telemetry"):
        line = f"event: {event}\n" f"data: {json.dumps(payload, separators=(',',':'))}\n\n"
        async with self.lock:
            for q in list(self.channels.get(key, set())):
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    try:
                        _ = q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    await q.put(line)

    async def keepalive(self, key: Key):
        line = f": keepalive {int(time.time())}\n\n"
        async with self.lock:
            for q in list(self.channels.get(key, set())):
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    pass

broker = SSEBroker()
