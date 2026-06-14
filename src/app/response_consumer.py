from typing import Any

import structlog

from app.metrics import ServiceMetrics
from domain.entities import OutgoingResponse
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


class ResponseConsumer:
    def __init__(
        self,
        clients: dict[str, TelegramClient],
        metrics: ServiceMetrics | None = None,
    ) -> None:
        self._clients = clients
        self._metrics = metrics

    async def handle(self, body: dict[str, Any]) -> None:
        response = OutgoingResponse.model_validate(body)
        client = self._clients.get(response.bot_id)
        if not client:
            logger.error("unknown bot in response", bot_id=response.bot_id)
            return

        if self._metrics:
            self._metrics.response_consumed()

        await self._send(client, response)

    async def _send(self, client: TelegramClient, response: OutgoingResponse) -> None:
        method_name = f"send_{response.response_type}"
        method = getattr(client, method_name, None)
        if not method:
            logger.error(
                "unknown response type",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
            return

        try:
            await method(chat_id=response.chat_id, **response.payload)
            if self._metrics:
                self._metrics.response_sent()
            logger.info(
                "response sent",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
        except Exception:
            logger.exception(
                "response send failed",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
            raise
