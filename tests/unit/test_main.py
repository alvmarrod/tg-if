from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.config import AppConfig, BotConfig, BrokerConfig


def _sample_config() -> AppConfig:
    return AppConfig(
        broker=BrokerConfig(
            host="localhost", port=5672, user="guest", password="guest"
        ),
        bots=[
            BotConfig(
                name="aibot",
                api_id=111,
                api_hash="hash",
                session_file="sessions/aibot.session",
            )
        ],
    )


class TestMain:
    @patch("main.ConfigLoader")
    @patch("main.ReceiverService")
    async def test_main_starts_and_stops(
        self, mock_receiver: MagicMock, mock_config_loader: MagicMock
    ) -> None:
        cfg = _sample_config()
        mock_config_loader.load.return_value = cfg
        instance = AsyncMock()
        mock_receiver.return_value = instance

        from main import main

        with patch("main.signal") as mock_signal:
            mock_signal.SIGINT = 2
            mock_signal.SIGTERM = 15
            mock_event = MagicMock()
            mock_event.wait = AsyncMock(return_value=None)
            mock_event.set = MagicMock()
            mock_event.is_set = MagicMock(return_value=False)

            with patch("main.asyncio.Event", return_value=mock_event):
                await main()

        mock_config_loader.load.assert_called_once()
        mock_receiver.assert_called_once_with(
            cfg, log_buffer=mock_receiver.call_args[1].get("log_buffer")
        )
        instance.start.assert_awaited_once()
        instance.stop.assert_awaited_once()

    @patch("main.ConfigLoader")
    @patch("main.ReceiverService")
    async def test_main_propagates_start_failure(
        self, mock_receiver: MagicMock, mock_config_loader: MagicMock
    ) -> None:
        cfg = _sample_config()
        mock_config_loader.load.return_value = cfg
        instance = AsyncMock()
        instance.start.side_effect = RuntimeError("start failed")
        mock_receiver.return_value = instance

        from main import main

        with patch("main.signal") as mock_signal:
            mock_signal.SIGINT = 2
            mock_signal.SIGTERM = 15
            mock_event = MagicMock()
            mock_event.wait = AsyncMock()
            mock_event.set = MagicMock()

            with patch("main.asyncio.Event", return_value=mock_event):
                with pytest.raises(RuntimeError, match="start failed"):
                    await main()

        instance.start.assert_awaited_once()
        instance.stop.assert_not_called()
