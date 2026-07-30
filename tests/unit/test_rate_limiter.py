from __future__ import annotations


from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from infrastructure.media.rate_limiter import (
    _SlidingWindowLimiter,
    _UploadRateLimiterKey,
    upload_rate_limit_middleware,
)


class TestSlidingWindowLimiter:
    def test_allows_under_limit(self) -> None:
        limiter = _SlidingWindowLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            assert limiter.allow("192.0.2.1") is True

    def test_blocks_over_limit(self) -> None:
        limiter = _SlidingWindowLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.allow("192.0.2.1")
        assert limiter.allow("192.0.2.1") is False

    def test_different_keys_independent(self) -> None:
        limiter = _SlidingWindowLimiter(max_requests=1, window_seconds=60)
        assert limiter.allow("a") is True
        assert limiter.allow("b") is True
        assert limiter.allow("a") is False

    def test_sliding_window_clears_old(self) -> None:
        limiter = _SlidingWindowLimiter(max_requests=2, window_seconds=0.1)
        assert limiter.allow("x") is True
        assert limiter.allow("x") is True
        assert limiter.allow("x") is False
        import time

        time.sleep(0.15)
        assert limiter.allow("x") is True


class TestRateLimitMiddleware:
    async def test_allows_non_upload_path(self) -> None:
        app = web.Application()
        app.middlewares.append(upload_rate_limit_middleware)  # type: ignore[arg-type]
        app.router.add_get("/health", _fake_handler)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200

    async def test_allows_upload_when_no_limiter(self) -> None:
        app = web.Application()
        app.middlewares.append(upload_rate_limit_middleware)  # type: ignore[arg-type]
        app.router.add_post("/upload/{bot_id}", _fake_handler)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/upload/testbot")
            assert resp.status == 200

    async def test_blocks_upload_when_rate_limited(self) -> None:
        limiter = _SlidingWindowLimiter(max_requests=1, window_seconds=60)
        app = web.Application()
        app[_UploadRateLimiterKey] = limiter
        app.middlewares.append(upload_rate_limit_middleware)  # type: ignore[arg-type]
        app.router.add_post("/upload/{bot_id}", _fake_handler)

        async with TestClient(TestServer(app)) as client:
            resp1 = await client.post("/upload/testbot")
            assert resp1.status == 200
            resp2 = await client.post("/upload/testbot")
            assert resp2.status == 429
            body = await resp2.json()
            assert "rate limit" in body["error"]

    async def test_x_forwarded_for_respected(self) -> None:
        limiter = _SlidingWindowLimiter(max_requests=1, window_seconds=60)
        app = web.Application()
        app[_UploadRateLimiterKey] = limiter
        app.middlewares.append(upload_rate_limit_middleware)  # type: ignore[arg-type]
        app.router.add_post("/upload/{bot_id}", _fake_handler)

        async with TestClient(TestServer(app)) as client:
            resp1 = await client.post(
                "/upload/testbot",
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
            assert resp1.status == 200
            resp2 = await client.post(
                "/upload/testbot",
                headers={"X-Forwarded-For": "10.0.0.2"},
            )
            assert resp2.status == 200
            resp3 = await client.post(
                "/upload/testbot",
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
            assert resp3.status == 429


async def _fake_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})
