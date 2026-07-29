from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aiohttp import web

from infrastructure.health import create_health_server, handle_health, handle_metrics
from infrastructure.media.upload_routes import BrokerKey, ClientsKey


def _body(resp: web.Response) -> Any:
    b = resp.body
    assert b is not None
    return json.loads(b.decode())


@pytest.fixture
def app() -> web.Application:
    return web.Application()


@pytest.fixture
def mock_request(app: web.Application) -> Mock:
    return Mock(spec=web.Request, app=app)


class TestHandleHealth:
    async def test_no_broker_no_clients(self, mock_request: Mock) -> None:
        resp = await handle_health(mock_request)
        assert resp.status == 200
        assert _body(resp) == {"status": "healthy"}

    async def test_broker_connected(
        self, app: web.Application, mock_request: Mock
    ) -> None:
        broker = AsyncMock()
        broker.health = AsyncMock(return_value=True)
        app[BrokerKey] = broker
        resp = await handle_health(mock_request)
        assert _body(resp)["broker"] == "connected"

    async def test_broker_disconnected(
        self, app: web.Application, mock_request: Mock
    ) -> None:
        broker = AsyncMock()
        broker.health = AsyncMock(return_value=False)
        app[BrokerKey] = broker
        resp = await handle_health(mock_request)
        assert _body(resp)["broker"] == "disconnected"

    async def test_clients_dict(self, app: web.Application, mock_request: Mock) -> None:
        client_a = MagicMock()
        client_a.health = AsyncMock(return_value=True)
        client_a.bot_id = "bota"
        client_b = MagicMock()
        client_b.health = AsyncMock(return_value=False)
        client_b.bot_id = "botb"
        app[ClientsKey] = {"bota": client_a, "botb": client_b}
        body = _body(await handle_health(mock_request))
        assert body["clients"]["bota"] == "connected"
        assert body["clients"]["botb"] == "disconnected"

    async def test_clients_iterable(
        self, app: web.Application, mock_request: Mock
    ) -> None:
        client_a = MagicMock()
        client_a.health = AsyncMock(return_value=True)
        client_a.bot_id = "bota"
        client_b = MagicMock()
        client_b.health = AsyncMock(return_value=False)
        client_b.bot_id = "botb"
        app[ClientsKey] = [client_a, client_b]
        body = _body(await handle_health(mock_request))
        assert body["clients"]["bota"] == "connected"
        assert body["clients"]["botb"] == "disconnected"

    async def test_clients_invalid_type_raises(
        self, app: web.Application, mock_request: Mock
    ) -> None:
        app[ClientsKey] = "not_a_dict_or_iterable"
        with pytest.raises(TypeError, match="Expected dict or iterable"):
            await handle_health(mock_request)

    async def test_dict_client_without_health_raises(
        self, app: web.Application, mock_request: Mock
    ) -> None:
        bad_client = MagicMock(spec=[])  # no health method
        app[ClientsKey] = {"bad": bad_client}
        with pytest.raises(
            TypeError, match="Expected client object with health method"
        ):
            await handle_health(mock_request)

    async def test_iterable_client_without_bot_id_raises(
        self, app: web.Application, mock_request: Mock
    ) -> None:
        bad_client = MagicMock(spec=["health"])  # has health but no bot_id
        bad_client.health = AsyncMock(return_value=True)
        app[ClientsKey] = [bad_client]
        with pytest.raises(
            TypeError, match="Expected client object with bot_id attribute"
        ):
            await handle_health(mock_request)


class TestHandleMetrics:
    async def test_returns_prometheus_text(self, mock_request: Mock) -> None:
        resp = await handle_metrics(mock_request)
        assert resp.status == 200
        b = resp.body
        assert b is not None
        text = b.decode()
        assert "text/plain" in resp.content_type
        assert len(text) > 0


class TestCreateHealthServer:
    async def test_server_creates_and_starts(self) -> None:
        site = await create_health_server(port=0)
        assert isinstance(site, web.TCPSite)
        await site.stop()

    async def test_server_extra_kwargs(self) -> None:
        site = await create_health_server(port=0, broker="test", clients=[])
        assert isinstance(site, web.TCPSite)
        await site.stop()
