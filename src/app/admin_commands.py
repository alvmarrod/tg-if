from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.log_buffer import LogBuffer
from app.media_config import MediaConfigManager
from app.metrics import ServiceMetrics
from domain.entities import (
    CommandEvent,
    MediaConfigRule,
    MediaScope,
    RoutingContext,
    TelegramEvent,
)
from infrastructure.broker import RabbitMQManager
from infrastructure.config import AppConfig
from infrastructure.media.storage import MediaStorage
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


def _parse_scope(scope_str: str) -> tuple[MediaScope | None, str | None]:
    if scope_str == "global":
        return MediaScope.GLOBAL, None
    if scope_str.startswith("chat:"):
        return MediaScope.CHAT, scope_str[5:]
    if scope_str.startswith("user:"):
        return MediaScope.USER, scope_str[5:]
    return None, None


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _parse_size(s: str) -> int | None:
    s = s.strip().upper()
    try:
        if s.endswith("GB"):
            return int(float(s[:-2]) * 1024 * 1024 * 1024)
        if s.endswith("MB"):
            return int(float(s[:-2]) * 1024 * 1024)
        if s.endswith("KB"):
            return int(float(s[:-2]) * 1024)
        return int(s)
    except ValueError:
        return None


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
        media_config: MediaConfigManager | None = None,
        storage: MediaStorage | None = None,
    ) -> None:
        self._admin = admin_client
        self._user_id = user_id
        self._clients = clients
        self._manager = manager
        self._config = config
        self._metrics = metrics
        self._log_buffer = log_buffer
        self._media_config = media_config
        self._storage = storage

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
        elif cmd == "media-eager":
            await self._cmd_media_eager(event.chat_id, args)
        elif cmd == "media-lazy":
            await self._cmd_media_lazy(event.chat_id, args)
        elif cmd == "media-config":
            await self._cmd_media_config(event.chat_id, args)
        elif cmd == "media-list":
            await self._cmd_media_list(event.chat_id, args)
        elif cmd == "media-stats":
            await self._cmd_media_stats(event.chat_id)
        elif cmd == "media-prune":
            await self._cmd_media_prune(event.chat_id, args)
        elif cmd == "media-purge":
            await self._cmd_media_purge(event.chat_id, args)
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
            "/log [count] — Recent logs (default 20)\n"
            "/media-eager --scope <s> [--type <t>] — Set eager download\n"
            "/media-lazy --scope <s> [--type <t>] — Set lazy download\n"
            "/media-config — List media config rules\n"
            "/media-list [--sort <col>:<dir>,...] — List cached media\n"
            "/media-stats — Media cache statistics\n"
            "/media-prune --keep-first N | --max-size N | --older-than Nd — Prune cache\n"
            "/media-purge [confirm] — Delete all cached media"
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

    async def _cmd_media_eager(self, chat_id: int, args: list[str]) -> None:
        if self._media_config is None:
            await self._admin.send_text(chat_id, "Media config not available")
            return
        kwargs = _parse_kwargs(args)
        scope_str = kwargs.get("scope")
        if not scope_str:
            await self._admin.send_text(
                chat_id,
                "Usage: /media-eager --scope global|chat:<id>|user:<id> [--type <t>]",
            )
            return

        scope, scope_id = _parse_scope(scope_str)
        if scope is None:
            await self._admin.send_text(chat_id, f"Invalid scope: {scope_str}")
            return

        types_str = kwargs.get("type", "all")
        content_types = [t.strip() for t in types_str.split(",")]

        rule = MediaConfigRule(
            scope=scope,
            scope_id=scope_id,
            content_types=content_types,
            action="eager",
        )
        self._media_config.add_rule(rule)
        await self._admin.send_text(
            chat_id,
            f"Eager download set: scope={scope_str}, type={types_str}",
        )

    async def _cmd_media_lazy(self, chat_id: int, args: list[str]) -> None:
        if self._media_config is None:
            await self._admin.send_text(chat_id, "Media config not available")
            return
        kwargs = _parse_kwargs(args)
        scope_str = kwargs.get("scope")
        if not scope_str:
            await self._admin.send_text(
                chat_id,
                "Usage: /media-lazy --scope global|chat:<id>|user:<id> [--type <t>]",
            )
            return

        scope, scope_id = _parse_scope(scope_str)
        if scope is None:
            await self._admin.send_text(chat_id, f"Invalid scope: {scope_str}")
            return

        types_str = kwargs.get("type", "all")
        content_types = [t.strip() for t in types_str.split(",")]

        rule = MediaConfigRule(
            scope=scope,
            scope_id=scope_id,
            content_types=content_types,
            action="lazy",
        )
        self._media_config.add_rule(rule)
        await self._admin.send_text(
            chat_id,
            f"Lazy download set: scope={scope_str}, type={types_str}",
        )

    async def _cmd_media_config(self, chat_id: int, args: list[str]) -> None:
        if self._media_config is None:
            await self._admin.send_text(chat_id, "Media config not available")
            return
        rules = self._media_config.list_rules()
        if not rules:
            await self._admin.send_text(chat_id, "No media config rules")
            return

        lines = ["Media config rules:"]
        for i, r in enumerate(rules, 1):
            sid = f":{r.scope_id}" if r.scope_id else ""
            lines.append(
                f"  {i}. {r.scope}{sid} types={','.join(r.content_types)} -> {r.action}"
            )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def _cmd_media_list(self, chat_id: int, args: list[str]) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        kwargs = _parse_kwargs(args)
        sort_spec = kwargs.get("sort", "size:desc")
        files = await self._storage.list_files()

        if not files:
            await self._admin.send_text(chat_id, "No cached media")
            return

        sort_cols = [s.strip() for s in sort_spec.split(",")]
        for col_dir in reversed(sort_cols):
            parts = col_dir.split(":")
            col = parts[0]
            reverse = len(parts) < 2 or parts[1] != "asc"
            if col == "size":
                files.sort(key=lambda f: f.size, reverse=reverse)
            elif col == "accesses":
                files.sort(key=lambda f: f.accesses, reverse=reverse)
            elif col == "lru":
                files.sort(
                    key=lambda f: f.last_access.timestamp() if f.last_access else 0,
                    reverse=reverse,
                )
            elif col == "stored_at":
                files.sort(key=lambda f: f.stored_at.timestamp(), reverse=reverse)

        lines = [
            "Cached media:",
            f"{'file_unique_id':<18} {'type':<6} {'size':>10} "
            f"{'accesses':>9} {'last_access':<20} {'stored_at':<20}",
        ]
        for f in files:
            la = f.last_access.strftime("%Y-%m-%d %H:%M") if f.last_access else "—"
            sa = f.stored_at.strftime("%Y-%m-%d %H:%M")
            size_str = _format_size(f.size)
            lines.append(
                f"{f.file_unique_id:<18} {f.ext:<6} {size_str:>10} "
                f"{f.accesses:>9} {la:<20} {sa:<20}"
            )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def _cmd_media_stats(self, chat_id: int) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        stats = await self._storage.stats()
        lines = [
            "Media cache statistics:",
            f"  Total files: {stats['total_files']}",
            f"  Total size:  {_format_size(stats['total_size_bytes'])}",
        ]
        by_type = stats.get("by_type", {})
        if by_type:
            lines.append("  By type:")
            for ext in sorted(by_type):
                info = by_type[ext]
                lines.append(
                    f"    .{ext:<5} {info['count']:>6} files, "
                    f"{_format_size(info['size_bytes'])}"
                )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def _cmd_media_prune(self, chat_id: int, args: list[str]) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        kwargs = _parse_kwargs(args)

        keep_first: int | None = None
        max_size: int | None = None
        older_than_days: int | None = None

        keep_str = kwargs.get("keep-first")
        if keep_str:
            try:
                keep_first = int(keep_str)
            except ValueError:
                await self._admin.send_text(
                    chat_id, f"Invalid --keep-first value: {keep_str}"
                )
                return

        max_size_str = kwargs.get("max-size")
        if max_size_str:
            max_size = _parse_size(max_size_str)
            if max_size is None:
                await self._admin.send_text(
                    chat_id, f"Invalid --max-size value: {max_size_str}"
                )
                return

        older_str = kwargs.get("older-than")
        if older_str:
            try:
                older_than_days = int(older_str.rstrip("d"))
            except ValueError:
                await self._admin.send_text(
                    chat_id, f"Invalid --older-than value: {older_str}"
                )
                return

        if keep_first is None and max_size is None and older_than_days is None:
            await self._admin.send_text(
                chat_id,
                "Usage: /media-prune --keep-first N | --max-size N[KB|MB|GB] | --older-than Nd",
            )
            return

        deleted = await self._storage.prune(
            keep_first=keep_first,
            max_size=max_size,
            older_than_days=older_than_days,
        )
        await self._admin.send_text(
            chat_id, f"Pruned {deleted} file{'s' if deleted != 1 else ''}"
        )

    async def _cmd_media_purge(self, chat_id: int, args: list[str]) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        if not args or args[0] != "confirm":
            stats = await self._storage.stats()
            await self._admin.send_text(
                chat_id,
                f"⚠️ This will delete all {stats['total_files']} cached files "
                f"({_format_size(stats['total_size_bytes'])}). "
                "Send /media-purge confirm to proceed.",
            )
            return

        deleted = await self._storage.purge()
        await self._admin.send_text(
            chat_id, f"Purged {deleted} file{'s' if deleted != 1 else ''}"
        )
