from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.log_buffer import LogBuffer
from app.metrics import ServiceMetrics
from domain.entities import CommandEvent, RoutingContext, TelegramEvent
from infrastructure.broker import RabbitMQManager
from infrastructure.config import AppConfig
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


def _parse_kwargs(args: list[str]) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 2
            else:
                kwargs[key] = ""
                i += 1
        else:
            i += 1
    return kwargs


def _format_uptime(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


class AdminCommandHandler:
    def __init__(
        self,
        *,
        admin_client: TelegramClient,
        user_id: int,
        clients: dict[str, TelegramClient],
        manager: RabbitMQManager,
        config: AppConfig,
        metrics: ServiceMetrics,
        log_buffer: LogBuffer | None = None,
    ) -> None:
        self._admin = admin_client
        self._user_id = user_id
        self._clients = clients
        self._manager = manager
        self._config = config
        self._metrics = metrics
        self._log_buffer = log_buffer

    async def handle(self, event: TelegramEvent, context: RoutingContext) -> None:
        if event.chat_id != self._user_id:
            return
        if not isinstance(event, CommandEvent):
            return

        cmd = event.command
        args = event.command_args

        if cmd == "help":
            await self._cmd_help(event.chat_id)
        elif cmd == "status":
            await self._cmd_status(event.chat_id)
        elif cmd == "bots":
            await self._cmd_bots(event.chat_id)
        elif cmd == "rules":
            await self._cmd_rules(event.chat_id, args)
        elif cmd == "log":
            await self._cmd_log(event.chat_id, args)
        else:
            await self._admin.send_text(
                event.chat_id,
                f"Unknown command: /{cmd}\nTry /help",
            )

    async def _cmd_help(self, chat_id: int) -> None:
        text = (
            "Available commands:\n"
            "/help — Show this message\n"
            "/status — Service status and metrics\n"
            "/bots — List configured bots\n"
            "/rules [--bot <name>] — Show routing rules\n"
            "/log [count] — Recent logs (default 20)"
        )
        await self._admin.send_text(chat_id, text)

    async def _cmd_status(self, chat_id: int) -> None:
        lines: list[str] = []

        uptime = datetime.now(timezone.utc) - self._metrics.started_at
        lines.append(
            f"\U0001f4ca Service Status  |  uptime: "
            f"{_format_uptime(int(uptime.total_seconds()))}"
        )
        lines.append("")

        lines.append("Connections:")
        try:
            broker_ok = await self._manager.health()
            lines.append(f"  broker       {'✅' if broker_ok else '❌'}")
        except Exception:
            lines.append("  broker       ❌ (error)")

        for name, client in self._clients.items():
            try:
                ok = await client.health()
                lines.append(f"  {name:<12} {'✅' if ok else '❌'}")
            except Exception:
                lines.append(f"  {name:<12} ❌ (error)")

        try:
            admin_ok = await self._admin.health()
            lines.append(f"  admin        {'✅' if admin_ok else '❌'}")
        except Exception:
            lines.append("  admin        ❌ (error)")

        lines.append("")
        lines.append("Incoming events:")
        for bot_id in sorted(self._metrics.bot_events.keys()):
            m = self._metrics.bot_events[bot_id]
            lines.append(
                f"  {bot_id:<12} recv: {m.received:<5} "
                f"\u2192 match: {m.matched:<5} "
                f"\u2192 publish: {m.published}"
            )
        if not self._metrics.bot_events:
            lines.append("  (no events yet)")

        lines.append("")
        r = self._metrics.responses
        lines.append("Outgoing responses:")
        lines.append(
            f"  consumed: {r.consumed} \u2192 sent: {r.sent} \u2192 failed: {r.failed}"
        )

        await self._admin.send_text(chat_id, "\n".join(lines))

    async def _cmd_bots(self, chat_id: int) -> None:
        lines = ["Configured bots:"]
        for bot_cfg in self._config.bots:
            lines.append(
                f"\u2022 {bot_cfg.name} \u2014 {len(bot_cfg.routing_rules)} rules"
            )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def _cmd_rules(self, chat_id: int, args: list[str]) -> None:
        kwargs = _parse_kwargs(args)
        bot_filter = kwargs.get("bot")

        lines: list[str] = []
        for bot_cfg in self._config.bots:
            if bot_filter and bot_cfg.name != bot_filter:
                continue
            if not bot_cfg.routing_rules:
                lines.append(f"No rules for {bot_cfg.name}")
                continue

            lines.append(f"Routing rules for {bot_cfg.name}:")
            for i, rule in enumerate(bot_cfg.routing_rules, 1):
                cond_parts: list[str] = []
                for key, val in rule.condition.items():
                    cond_parts.append(f"{key}={val}")
                cond_str = "(catch-all)" if not cond_parts else " & ".join(cond_parts)
                lines.append(f"  {i}. {cond_str} \u2192 {rule.target}")
            lines.append("")

        if not lines:
            lines.append("No bots configured")

        await self._admin.send_text(chat_id, "\n".join(lines).strip())

    async def _cmd_log(self, chat_id: int, args: list[str]) -> None:
        n = 20
        for a in args:
            try:
                n = int(a)
            except ValueError:
                pass

        if self._log_buffer is None:
            await self._admin.send_text(chat_id, "Log buffer not available")
            return

        entries = self._log_buffer.recent(n)
        if not entries:
            await self._admin.send_text(chat_id, "No log entries")
            return

        lines = [f"\U0001f4cb Recent logs (last {len(entries)}):"]
        for e in reversed(entries):
            ts = str(e.get("timestamp", ""))[11:19]
            level = e.get("level", "INFO")
            event = e.get("event", "")
            extra = e.get("extra", {})
            extra_str = "  ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
            lines.append(f"{ts} {level:<5} {event}  {extra_str}")

        await self._admin.send_text(chat_id, "\n".join(lines))
