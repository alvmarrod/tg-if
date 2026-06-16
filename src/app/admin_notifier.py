from __future__ import annotations

from typing import Any

import structlog

from domain.schemas import AdminSignalType
from infrastructure.config import AdminBotConfig, BotConfig
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


def _format_signal(signal_type: AdminSignalType, **kwargs: Any) -> str:
    if signal_type == AdminSignalType.RESPONSE_FAILED:
        body = kwargs.get("body", {})
        exc = kwargs.get("exc", "")
        return (
            f"⚠️ Response Failed\n"
            f"Bot: {body.get('bot_id', '?')}\n"
            f"Type: {body.get('response_type', '?')}\n"
            f"Chat: {body.get('chat_id', '?')}\n"
            f"Error: {exc}\n"
            f"ID: {body.get('response_id', '?')}"
        )

    if signal_type == AdminSignalType.COMPONENT_CONNECTED:
        return f"✅ {kwargs.get('component', '?')} connected"

    if signal_type == AdminSignalType.COMPONENT_DISCONNECTED:
        return f"❌ {kwargs.get('component', '?')} disconnected"

    if signal_type == AdminSignalType.CONFIG_WARNING:
        msg = kwargs.get("message", "?")
        body = kwargs.get("body", {})
        return f"⚠️ Config Warning\nMessage: {msg}\nBody: {body}"

    return f"Unknown signal: {signal_type}"


class AdminNotifier:
    def __init__(
        self,
        config: AdminBotConfig,
        client: TelegramClient | None = None,
    ) -> None:
        self._config = config
        self._user_id = config.user_id
        if client is not None:
            self._client = client
        else:
            bot_cfg = BotConfig(
                name=config.name,
                api_id=config.api_id,
                api_hash=config.api_hash,
                session_file=config.session_file,
            )
            self._client = TelegramClient(bot_cfg)

    async def start(self) -> None:
        await self._client.start()

    async def stop(self) -> None:
        await self._client.stop()

    async def health(self) -> bool:
        return await self._client.health()

    async def notify(self, signal_type: AdminSignalType, **kwargs: Any) -> None:
        text = _format_signal(signal_type, **kwargs)
        try:
            await self._client.send_text(self._user_id, text)
            logger.info("admin notification sent", signal=signal_type.value)
        except Exception:
            logger.exception("admin notification failed", signal=signal_type.value)
