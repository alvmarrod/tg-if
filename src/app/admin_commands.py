from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import structlog

from app.event_dispatcher import EventDispatcher
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
from domain.rules import RoutingRule
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
        dispatcher: EventDispatcher,
        log_buffer: LogBuffer | None = None,
        media_config: MediaConfigManager | None = None,
        storage: MediaStorage | None = None,
        on_shutdown: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._admin = admin_client
        self._user_id = user_id
        self._clients = clients
        self._manager = manager
        self._config = config
        self._metrics = metrics
        self._dispatcher = dispatcher
        self._log_buffer = log_buffer
        self._media_config = media_config
        self._storage = storage
        self._on_shutdown = on_shutdown

    async def handle(self, event: TelegramEvent, context: RoutingContext) -> None:
        if event.chat_id != self._user_id:
            return
        if not isinstance(event, CommandEvent):
            return

        cmd = event.command
        args = event.command_args

        if cmd == "help":
            await self._cmd_help(event.chat_id)
        elif cmd == "ping":
            await self._cmd_ping(event.chat_id)
        elif cmd == "status":
            await self._cmd_status(event.chat_id)
        elif cmd == "target":
            await self._cmd_target(event.chat_id, args)
        elif cmd == "bots":
            await self._cmd_bots(event.chat_id)
        elif cmd == "rules":
            await self._cmd_rules(event.chat_id, args)
        elif cmd == "rule-add":
            await self._cmd_rule_add(event.chat_id, args)
        elif cmd == "rule-remove":
            await self._cmd_rule_remove(event.chat_id, args)
        elif cmd == "log":
            await self._cmd_log(event.chat_id, args)
        elif cmd == "shutdown":
            await self._cmd_shutdown(event.chat_id)
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
            "/ping — Liveness check\n"
            "/status — Service control panel\n"
            "/target <name> — Detail for a routing target\n"
            "/bots — List configured bots\n"
            "/rules [--bot <name>] — Show routing rules\n"
            "/rule-add --bot <n> --target <key> [--condition k=v ...] — Append rule\n"
            "/rule-remove --bot <n> --index <i> — Remove rule by index\n"
            "/log [count] — Recent logs (default 20)\n"
            "/shutdown — Graceful service stop\n"
            "/media-eager --scope <s> [--type <t>] — Set eager download\n"
            "/media-lazy --scope <s> [--type <t>] — Set lazy download\n"
            "/media-config — List media config rules\n"
            "/media-list [--sort <col>:<dir>,...] — List cached media\n"
            "/media-stats — Media cache statistics\n"
            "/media-prune --keep-first N | --max-size N | --older-than Nd — Prune cache\n"
            "/media-purge [confirm] — Delete all cached media"
        )
        await self._admin.send_text(chat_id, text)

    async def _cmd_ping(self, chat_id: int) -> None:
        await self._admin.send_text(chat_id, "pong")

    async def _cmd_target(self, chat_id: int, args: list[str]) -> None:
        if not args:
            await self._admin.send_text(chat_id, "Usage: /target <name>")
            return
        name = args[0]
        stat = self._metrics.get_target(name)
        if stat is None:
            await self._admin.send_text(chat_id, f"No data for target: {name}")
            return

        total = sum(t.events for t in self._metrics.per_target.values())
        pct = (stat.events / total * 100) if total > 0 else 0.0
        last_str = (
            f"{stat.last_event.strftime('%H:%M:%S')} "
            f"({int((datetime.now(timezone.utc) - stat.last_event).total_seconds())}s ago)"
            if stat.last_event
            else "—"
        )
        bots_str = (
            ", ".join(
                f"{b} (rule #{i + 1})"
                for b in stat.bots
                for i, r in enumerate(self._dispatcher.get_rules(b).get(b, []))
                if r.target == name
            )
            or "—"
        )

        text = (
            f"\U0001f3af Target: {name}\n"
            f"  Events (last 1h):  {stat.events}  ({pct:.1f}% of total)\n"
            f"  Last event:        {last_str}\n"
            f"  Published by:      {bots_str}"
        )
        await self._admin.send_text(chat_id, text)

    async def _cmd_status(self, chat_id: int) -> None:
        lines: list[str] = []

        uptime = datetime.now(timezone.utc) - self._metrics.started_at
        lines.append("\U0001f4ca Service Control Panel")
        lines.append("")
        lines.append(
            f"\u23f1\ufe0f Uptime: {_format_uptime(int(uptime.total_seconds()))}"
        )
        lines.append("")

        lines.append("\U0001f50c Connections:")
        conn_parts: list[str] = []
        try:
            conn_parts.append(
                f"broker       {'✅' if await self._manager.health() else '❌'}"
            )
        except Exception:
            conn_parts.append("broker       ❌")
        for name, client in self._clients.items():
            try:
                ok = await client.health()
                conn_parts.append(f"{name:<12} {'✅' if ok else '❌'}")
            except Exception:
                conn_parts.append(f"{name:<12} ❌")
        try:
            admin_ok = await self._admin.health()
            conn_parts.append(f"admin        {'✅' if admin_ok else '❌'}")
        except Exception:
            conn_parts.append("admin        ❌")

        for i in range(0, len(conn_parts), 2):
            left = conn_parts[i]
            right = conn_parts[i + 1] if i + 1 < len(conn_parts) else ""
            lines.append(f"  {left:<30} {right}")
        lines.append("")

        lines.append("\U0001f4e5 Event Summary (last 1h):")
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
        lines.append("\U0001f4e4 Outgoing Responses:")
        lines.append(
            f"  consumed: {r.consumed} \u2192 sent: {r.sent} \u2192 failed: {r.failed}"
        )

        lines.append("")
        target_stats = self._metrics.get_target_stats()
        lines.append("\U0001f3af Active Targets (last 1h):")
        if target_stats:
            total = sum(t.events for t in target_stats)
            shown = target_stats[:5]
            hidden = target_stats[5:]
            for ts in shown:
                pct = (ts.events / total * 100) if total > 0 else 0.0
                lines.append(f"  {ts.name:<20} {ts.events:<8} events  ({pct:.1f}%)")
            if hidden:
                hidden_events = sum(h.events for h in hidden)
                hidden_pct = (hidden_events / total * 100) if total > 0 else 0.0
                lines.append(
                    f"  {len(hidden)} more\u2026{' ':<20} {hidden_events:<8} events  ({hidden_pct:.1f}%)"
                )
        else:
            lines.append("  (no targets yet)")

        if self._storage is not None:
            try:
                stats = await self._storage.stats()
                lines.append("")
                lines.append("\U0001f5c4\ufe0f Media Cache:")
                lines.append(
                    f"  {stats['total_files']} files ({_format_size(stats['total_size_bytes'])})"
                )
            except Exception:
                pass

        total_rules = sum(len(rules) for rules in self._dispatcher.get_rules().values())
        lines.append("")
        lines.append(f"\U0001f39a\ufe0f Config Rules: {total_rules} active")

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

    async def _cmd_rule_add(self, chat_id: int, args: list[str]) -> None:
        kwargs = _parse_kwargs(args)
        bot_name = kwargs.get("bot")
        target = kwargs.get("target")
        condition_str = kwargs.get("condition")

        if not bot_name or not target:
            await self._admin.send_text(
                chat_id,
                "Usage: /rule-add --bot <name> --target <key> [--condition k=v ...]",
            )
            return

        condition: dict[str, str] = {}
        if condition_str:
            for pair in condition_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    condition[k.strip()] = v.strip()

        rule = RoutingRule(condition=condition, target=target)
        self._dispatcher.add_rule(bot_name, rule)
        try:
            await self._write_snapshot()
        except Exception:
            logger.exception("snapshot write failed")
        await self._admin.send_text(
            chat_id,
            f"Rule added to {bot_name}: {condition or '(catch-all)'} \u2192 {target}",
        )

    async def _cmd_rule_remove(self, chat_id: int, args: list[str]) -> None:
        kwargs = _parse_kwargs(args)
        bot_name = kwargs.get("bot")
        index_str = kwargs.get("index")

        if not bot_name or index_str is None:
            await self._admin.send_text(
                chat_id,
                "Usage: /rule-remove --bot <name> --index <i>",
            )
            return

        try:
            idx = int(index_str) - 1
        except ValueError:
            await self._admin.send_text(chat_id, f"Invalid index: {index_str}")
            return

        removed = self._dispatcher.remove_rule(bot_name, idx)
        if removed is None:
            await self._admin.send_text(
                chat_id, f"No rule at index {index_str} for {bot_name}"
            )
            return

        try:
            await self._write_snapshot()
        except Exception:
            logger.exception("snapshot write failed")
        await self._admin.send_text(
            chat_id,
            f"Rule {index_str} removed from {bot_name}: "
            f"{removed.condition or '(catch-all)'} \u2192 {removed.target}",
        )

    async def _cmd_shutdown(self, chat_id: int) -> None:
        await self._admin.send_text(chat_id, "\U0001f6d1 Shutting down\u2026")
        if self._on_shutdown:
            await self._on_shutdown()

    async def _write_snapshot(self) -> None:
        bots_dir = Path("config")
        bots_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_path = bots_dir / f"bots_{timestamp}.json"

        bots_data: list[dict[str, object]] = []
        for bot_cfg in self._config.bots:
            rules = self._dispatcher.get_rules(bot_cfg.name).get(bot_cfg.name, [])
            bots_data.append(
                {
                    "name": bot_cfg.name,
                    "api_id": bot_cfg.api_id,
                    "api_hash": bot_cfg.api_hash,
                    "session_file": bot_cfg.session_file,
                    "routing_rules": [
                        {"condition": r.condition, "target": r.target} for r in rules
                    ],
                }
            )

        admin_data = None
        if self._config.admin is not None:
            admin_data = {
                "name": self._config.admin.name,
                "api_id": self._config.admin.api_id,
                "api_hash": self._config.admin.api_hash,
                "session_file": self._config.admin.session_file,
                "user_id": self._config.admin.user_id,
            }

        snapshot = {
            "bots": bots_data,
            "admin": admin_data,
        }
        try:
            snapshot_path.write_text(json.dumps(snapshot, indent=2, default=str))
            logger.info("rules snapshot written", path=str(snapshot_path))
        except Exception:
            logger.exception("failed to write rules snapshot", path=str(snapshot_path))

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
