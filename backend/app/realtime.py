"""The event hub: remembers recent events and pushes new ones to every browser."""
import asyncio
import logging
from collections import deque
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("graphguard.realtime")


class EventHub:
    SEND_TIMEOUT = 2.0  # a client that can't take a message in 2s is dropped

    def __init__(self, buffer_size: int = 500):
        self._connections: set[WebSocket] = set()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=buffer_size)  # recent events
        self._seq = 0  # every event gets the next number: 1, 2, 3 ...
        self._lock = asyncio.Lock()  # one publish/connect at a time keeps order exact

    @property
    def current_seq(self) -> int:
        return self._seq

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def publish(self, event_type: str, data: Any) -> dict[str, Any]:
        async with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "type": event_type, "data": data}
            self._buffer.append(event)
            await self._send_to_all(event)
            return event

    async def connect(self, ws: WebSocket, last_seq: int | None) -> None:
        """Accept a client. If it says 'my last event was N', send what it missed."""
        await ws.accept()
        async with self._lock:
            oldest = self._buffer[0]["seq"] if self._buffer else self._seq + 1
            missed: list[dict[str, Any]] = []
            if last_seq is None:
                greeting = {"type": "hello", "current_seq": self._seq, "replayed": 0}
            elif last_seq > self._seq or last_seq + 1 < oldest:
                # Server restarted, or the client was away longer than our memory.
                greeting = {"type": "resync_required", "current_seq": self._seq}
            else:
                missed = [e for e in self._buffer if e["seq"] > last_seq]
                greeting = {"type": "hello", "current_seq": self._seq, "replayed": len(missed)}

            for message in [greeting, *missed]:
                if not await self._send(ws, message):
                    return  # client vanished while we were catching it up
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def _send(self, ws: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=self.SEND_TIMEOUT)
            return True
        except Exception as exc:  # disconnected, timed out, anything: drop this client only
            log.info("dropping websocket client: %r", exc)
            return False

    async def _send_to_all(self, event: dict[str, Any]) -> None:
        clients = list(self._connections)
        results = await asyncio.gather(*(self._send(ws, event) for ws in clients))
        for ws, ok in zip(clients, results):
            if not ok:
                self._connections.discard(ws)