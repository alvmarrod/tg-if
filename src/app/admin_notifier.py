from __future__ import annotations

from typing import Any

import structlog

from domain.schemas import AdminSignalType
from infrastructure.config import AdminBotConfig, BotConfig
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


def _format_signal(signal_type: AdminSignalType, **kwargs: Any) -> str:
    if signal_type == AdminSignalType.RESPONSE_FAILED:
        body = kwargs.get("body")
        if body is None:
            raise ValueError("RESPONSE_FAILED signal requires 'body'")
        exc = kwargs.get("exc")
        if exc is None:
            raise ValueError("RESPONSE_FAILED signal requires 'exc'")
        bot_id = body.get("bot_id")
        if bot_id is None:
            raise ValueError("RESPONSE_FAILED signal requires 'bot_id' in body")
        response_type = body.get("response_type")
        if response_type is None:
            raise ValueError("RESPONSE_FAILED signal requires 'response_type' in body")
        chat_id = body.get("chat_id")
        if chat_id is None:
            raise ValueError("RESPONSE_FAILED signal requires 'chat_id' in body")
        response_id = body.get("response_id")
        if response_id is None:
            raise ValueError("RESPONSE_FAILED signal requires 'response_id' in body")
        return (
            f"⚠️ Response Failed\n"
            f"Bot: {bot_id}\n"
            f"Type: {response_type}\n"
            f"Chat: {chat_id}\n"
            f"Error: {exc}\n"
            f"ID: {response_id}"
        )

    if signal_type == AdminSignalType.COMPONENT_CONNECTED:
        component = kwargs.get("component")
        if component is None:
            raise ValueError("COMPONENT_CONNECTED signal requires 'component'")
        return f"✅ {component} connected"

    if signal_type == AdminSignalType.COMPONENT_DISCONNECTED:
        component = kwargs.get("component")
        if component is None:
            raise ValueError("COMPONENT_DISCONNECTED signal requires 'component'")
        return f"❌ {component} disconnected"

    if signal_type == AdminSignalType.CONFIG_WARNING:
        msg = kwargs.get("message")
        if msg is None:
            raise ValueError("CONFIG_WARNING signal requires 'message'")
        body = kwargs.get("body")
        if body is None:
            raise ValueError("CONFIG_WARNING signal requires 'body'")
        return f"⚠️ Config Warning\nMessage: {msg}\nBody: {body}"

    return f"Unknown signal: {signal_type}"


class AdminNotifier:
    def __init__(
        self,
        config: AdminBotConfig,
        client: TelegramClient | None = None,
    ) -> None:
        """Initialize the admin notifier."""
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
        """Start the admin notifier."""
        await self._client.start()

    async def stop(self) -> None:
        """Stop the admin notifier."""
        await self._client.stop()

    async def health(self) -> bool:
        """Check if the admin notifier is healthy."""
        return await self._client.health()

    async def notify(self, signal_type: AdminSignalType, **kwargs: Any) -> None:
        """Send an admin notification."""
        try:
            text = _format_signal(signal_type, **kwargs)
            await self._client.send_text(self._user_id, text)
            logger.info("admin notification sent", signal=signal_type.value)
        except Exception:
            logger.exception("admin notification failed", signal=signal_type.value)
