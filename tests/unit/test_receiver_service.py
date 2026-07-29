from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.receiver_service import ReceiverService
from infrastructure.config import AppConfig, BotConfig, BrokerConfig


@pytest.fixture
def tmp_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        broker=BrokerConfig(host="localhost", port=5672),
        bots=[],
        media_cache_path=str(tmp_path / "media"),
        media_config_path=str(tmp_path / "media_config.json"),
        upload_db_path=str(tmp_path / "uploads.db"),
        upload_storage_path=str(tmp_path / "uploads"),
        export_storage_path=str(tmp_path / "exports"),
    )


def _cfg(tmp_path: Path, bots: list[BotConfig] | None = None) -> AppConfig:
    return AppConfig(
        broker=BrokerConfig(host="localhost", port=5672),
        bots=bots or [],
        media_cache_path=str(tmp_path / "media"),
        media_config_path=str(tmp_path / "media_config.json"),
        upload_db_path=str(tmp_path / "uploads.db"),
        upload_storage_path=str(tmp_path / "uploads"),
        export_storage_path=str(tmp_path / "exports"),
    )


class TestInit:
    def test_creates_clients_for_each_bot(self, tmp_path: Path) -> None:
        bots = [
            BotConfig(
                name="bota",
                api_id=1,
                api_hash="a",
                session_file="sessions/bota.session",
            ),
            BotConfig(
                name="botb",
                api_id=2,
                api_hash="b",
                session_file="sessions/botb.session",
            ),
        ]
        svc = ReceiverService(_cfg(tmp_path, bots))
        assert "bota" in svc._clients
        assert "botb" in svc._clients
        assert svc._user_client is None
        assert svc._notifier is None

    def test_user_client_skipped_when_no_config(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        assert svc._user_client is None


class TestStart:
    async def test_start_already_running(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        svc._running = True
        with patch.object(svc, "_manager"):
            await svc.start()  # should not raise

    async def test_start_broker_failure(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        svc._manager.connect = AsyncMock(side_effect=ConnectionError("broker down"))
        with pytest.raises(ConnectionError, match="broker down"):
            await svc.start()

    async def _prepare_start(self, svc: ReceiverService) -> None:
        """Replace infrastructure with mocks so start() can proceed."""
        svc._manager = AsyncMock()
        conn = MagicMock()
        conn.is_closed = False
        svc._manager.connection = conn
        svc._consumer = AsyncMock()
        svc._consumer.start = AsyncMock()
        svc._upload_registry.connect = MagicMock()
        for client in svc._clients.values():
            client.start = AsyncMock()

    async def _patch_consumer(self) -> AsyncMock:
        """Mock Consumer so start() doesn't need a real AMQP connection."""
        mc = AsyncMock()
        mc.start = AsyncMock()
        return mc

    async def test_start_with_bots(self, tmp_path: Path) -> None:
        bot_cfg = BotConfig(
            name="testbot",
            api_id=1,
            api_hash="h",
            session_file="sessions/testbot.session",
        )
        svc = ReceiverService(_cfg(tmp_path, [bot_cfg]))
        mock_consumer = await self._patch_consumer()
        with (
            patch.object(svc, "_manager", AsyncMock()),
            patch.object(svc, "_consumer", mock_consumer),
            patch.object(svc, "_upload_registry", MagicMock()),
            patch("app.receiver_service.Consumer", return_value=mock_consumer),
            patch("app.receiver_service.create_health_server") as mock_hs,
        ):
            svc._upload_registry.connect = MagicMock()
            mock_hs.return_value = AsyncMock()
            for client in svc._clients.values():
                client.start = AsyncMock()
            await svc.start()
        assert svc._started is True
        assert svc._running is True
        for client in svc._clients.values():
            client.start.assert_awaited_once()

    async def test_start_bot_failure_degrades(self, tmp_path: Path) -> None:
        bot_cfg = BotConfig(
            name="broken",
            api_id=1,
            api_hash="h",
            session_file="sessions/broken.session",
        )
        svc = ReceiverService(_cfg(tmp_path, [bot_cfg]))
        mock_consumer = await self._patch_consumer()
        with (
            patch.object(svc, "_manager", AsyncMock()),
            patch.object(svc, "_consumer", mock_consumer),
            patch.object(svc, "_upload_registry", MagicMock()),
            patch("app.receiver_service.Consumer", return_value=mock_consumer),
            patch("app.receiver_service.create_health_server") as mock_hs,
        ):
            svc._upload_registry.connect = MagicMock()
            mock_hs.return_value = AsyncMock()
            client = list(svc._clients.values())[0]
            client.start = AsyncMock(side_effect=Exception("auth failed"))
            await svc.start()
        assert "broken" not in svc._clients
        assert svc._running is True

    async def test_start_user_client_failure_sets_none(self, tmp_path: Path) -> None:
        bot_cfg = BotConfig(
            name="testbot",
            api_id=1,
            api_hash="h",
            session_file="sessions/testbot.session",
        )
        cfg = _cfg(tmp_path, [bot_cfg])
        svc = ReceiverService(cfg)
        mock_consumer = await self._patch_consumer()
        with (
            patch.object(svc, "_manager", AsyncMock()),
            patch.object(svc, "_consumer", mock_consumer),
            patch.object(svc, "_upload_registry", MagicMock()),
            patch("app.receiver_service.Consumer", return_value=mock_consumer),
            patch("app.receiver_service.create_health_server") as mock_hs,
        ):
            svc._upload_registry.connect = MagicMock()
            mock_hs.return_value = AsyncMock()
            for client in svc._clients.values():
                client.start = AsyncMock()
            svc._user_client = AsyncMock()
            svc._user_client.start = AsyncMock(side_effect=Exception("bad session"))
            await svc.start()
        assert svc._user_client is None


class TestShutdown:
    async def test_shutdown_not_running(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        await svc.shutdown()  # should not raise

    async def test_shutdown_stops_consumers_and_clients(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        health_site = AsyncMock()
        svc._running = True
        svc._health_site = health_site
        svc._health_task = AsyncMock()
        svc._health_task.done = MagicMock(return_value=False)
        svc._consumer = AsyncMock()
        svc._consumer.stop = AsyncMock()
        svc._upload_registry = MagicMock()
        svc._manager = AsyncMock()
        svc._clients = {"b": AsyncMock()}
        svc._clients["b"].stop = AsyncMock()

        await svc.shutdown()

        health_site.stop.assert_awaited_once()
        svc._consumer.stop.assert_awaited_once()
        svc._clients["b"].stop.assert_awaited_once()
        svc._upload_registry.close.assert_called_once()
        svc._manager.disconnect.assert_awaited_once()
        assert svc._running is False

    async def test_stop_calls_shutdown_and_notifier_stop(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        svc._running = True
        svc._health_site = AsyncMock()
        svc._health_task = AsyncMock()
        svc._health_task.done = MagicMock(return_value=True)
        svc._consumer = AsyncMock()
        svc._upload_registry = MagicMock()
        svc._manager = AsyncMock()
        svc._notifier = AsyncMock()
        svc._clients = {}

        await svc.stop()

        svc._notifier.stop.assert_awaited_once()


class TestRestart:
    async def test_restart_shuts_down_and_exits(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        svc._running = True
        svc._health_site = AsyncMock()
        svc._health_task = AsyncMock()
        svc._health_task.done = MagicMock(return_value=True)
        svc._consumer = AsyncMock()
        svc._upload_registry = MagicMock()
        svc._manager = AsyncMock()
        svc._clients = {}

        with pytest.raises(SystemExit) as exc:
            await svc.restart()
        assert exc.value.code == 0


class TestOnEvent:
    async def test_on_event_dispatches_and_triggers_downloader(
        self, tmp_path: Path
    ) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        svc._dispatcher = AsyncMock()
        svc._media_downloader = AsyncMock()
        event = MagicMock()
        event.bot_id = "testbot"
        context = MagicMock()

        await svc._on_event(event, context)

        svc._dispatcher.dispatch.assert_awaited_once_with(event, context)
        svc._media_downloader.on_event.assert_awaited_once_with(event, context)

    async def test_on_event_downloader_failure_re_raises(self, tmp_path: Path) -> None:
        svc = ReceiverService(_cfg(tmp_path))
        svc._dispatcher = AsyncMock()
        svc._media_downloader = AsyncMock()
        svc._media_downloader.on_event = AsyncMock(
            side_effect=RuntimeError("dl failed")
        )
        event = MagicMock()
        event.bot_id = "testbot"

        with pytest.raises(RuntimeError, match="dl failed"):
            await svc._on_event(event, MagicMock())
