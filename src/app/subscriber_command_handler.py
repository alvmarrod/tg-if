import json
from typing import Any

import structlog
from aio_pika import Message

from app.bot_command_registry import BotCommandRegistry
from domain.entities import (
    SubscriberCommandEnvelope,
    SubscriberCommandResponse,
)
from infrastructure.broker.rabbitmq import RabbitMQManager
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


class SubscriberCommandHandler:
    def __init__(
        self,
        registry: BotCommandRegistry,
        clients: dict[str, TelegramClient],
        manager: RabbitMQManager,
    ) -> None:
        self._registry = registry
        self._clients = clients
        self._manager = manager

    async def handle(self, body: dict[str, Any]) -> None:
        try:
            envelope = SubscriberCommandEnvelope.model_validate(body)
        except Exception:
            logger.exception("invalid subscriber command envelope")
            return

        client = self._clients.get(envelope.bot_id)
        if not client:
            logger.error(
                "unknown bot in subscriber command",
                bot_id=envelope.bot_id,
                subscriber_id=envelope.subscriber_id,
            )
            await self._reply(
                envelope.reply_to,
                SubscriberCommandResponse(
                    status="nok",
                    conflicts=[f"unknown bot '{envelope.bot_id}'"],
                ),
            )
            return

        if envelope.action == "register":
            result = self._registry.register(
                envelope.bot_id, envelope.subscriber_id, envelope.commands
            )
        elif envelope.action == "deregister":
            result = self._registry.deregister(envelope.bot_id, envelope.subscriber_id)
        else:
            logger.error(
                "unknown action in subscriber command",
                action=envelope.action,
            )
            return

        if result.status == "ok":
            merged = self._registry.get_commands(envelope.bot_id)
            try:
                await client.set_bot_commands(
                    [(c["command"], c["description"]) for c in merged]
                )
            except Exception:
                logger.exception(
                    "set_bot_commands failed after registration",
                    bot_id=envelope.bot_id,
                )
                result = SubscriberCommandResponse(
                    status="nok",
                    conflicts=["set_bot_commands call failed"],
                )

        await self._reply(envelope.reply_to, result)

    async def _reply(
        self,
        reply_to: str | None,
        response: SubscriberCommandResponse,
    ) -> None:
        if not reply_to:
            return
        conn = self._manager.connection
        if not conn or conn.is_closed:
            logger.warning("cannot reply: broker not connected")
            return
        channel = await conn.channel()
        try:
            await channel.default_exchange.publish(
                Message(
                    body=json.dumps(response.model_dump()).encode(),
                    delivery_mode=2,
                ),
                routing_key=reply_to,
            )
        finally:
            await channel.close()
