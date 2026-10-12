"""A small in-memory rate limiter for the expensive endpoints.

It counts requests per client in a sliding 60-second window. State lives in this
process's memory, which is why the app runs with one worker (see README)."""
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from app.config import get_settings

WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client: str, limit: int) -> float | None:
        """Record a hit. Returns None if allowed, or seconds to wait if the limit is exceeded."""
        now = self._clock()
        hits = self._hits[client]
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            return max(1.0, WINDOW_SECONDS - (now - hits[0]))
        hits.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def rate_limited(request: Request) -> None:
    """FastAPI dependency: add to the routes that are costly to run."""
    client = request.client.host if request.client else "unknown"
    settings = getattr(request.app.state, "settings", None) or get_settings()
    wait = limiter.check(client, settings.rate_limit_per_minute)
    if wait is not None:
        raise HTTPException(429, "Too many requests. Please slow down.", headers={"Retry-After": str(int(wait) + 1)})
