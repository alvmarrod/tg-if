"""Per-IP sliding-window rate limiter for HTTP endpoints."""

from __future__ import annotations

import time
from collections import defaultdict

from aiohttp import web


@web.middleware
async def upload_rate_limit_middleware(
    request: web.Request, handler: web.AbstractResource
) -> web.StreamResponse:
    if request.path.startswith("/upload/"):
        limiter: _SlidingWindowLimiter | None = request.app.get(_UploadRateLimiterKey)
        if limiter is not None and not limiter.allow(_client_ip(request)):
            return web.json_response(
                {"error": "rate limit exceeded, try again later"},
                status=429,
            )
    return await handler(request)  # type: ignore[operator, no-any-return]


_UploadRateLimiterKey = __name__ + ".upload_rate_limiter"


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    transport = request.transport
    if transport is not None:
        peername = transport.get_extra_info("peername")
        if peername is not None:
            return str(peername[0])
    return "unknown"


class _SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._buckets: defaultdict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        bucket = self._buckets[key]
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True
