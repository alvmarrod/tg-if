"""Chat/export admin commands (chats, export, callbacks)."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from domain.entities import (
    CallbackQueryEvent,
    ChatInfo,
    ChatType,
    ExportState,
)

from app.admin_commands_utils import _parse_kwargs

logger = structlog.get_logger()


class ExportCommandDelegate:
    def __init__(
        self,
        *,
        admin: Any,
        clients: dict[str, Any],
        config: Any,
        chat_exporter: Any | None = None,
    ) -> None:
        self._admin = admin
        self._clients = clients
        self._config = config
        self._chat_exporter = chat_exporter
        self._chats_search: dict[int, str] = {}

    _ITEMS_PER_PAGE = 15

    async def _collect_chats(self) -> list[ChatInfo]:
        if not self._clients:
            return []

        all_chats: list[ChatInfo] = []
        seen_ids: set[int] = set()

        for bot_name, client in self._clients.items():
            try:
                dialogs = await client.get_dialogs()
            except Exception:
                logger.warning("Failed to get known chats", bot=bot_name, exc_info=True)
                continue
            for d in dialogs:
                if d["chat_id"] in seen_ids:
                    continue
                seen_ids.add(d["chat_id"])
                try:
                    chat_type = ChatType(d["type"])
                except ValueError:
                    logger.warning(
                        "Unknown chat type", type=d["type"], chat_id=d["chat_id"]
                    )
                    continue
                ci = ChatInfo(
                    chat_id=d["chat_id"],
                    title=d["title"],
                    chat_type=chat_type,
                    members=d["members"],
                    can_read=d["can_read"],
                    can_write=d["can_write"],
                    exportable=d["can_read"],
                    bot_id=bot_name,
                )
                all_chats.append(ci)

        all_chats.sort(key=lambda c: c.title.lower())
        return all_chats

    async def cmd_chats(self, chat_id: int, args: list[str]) -> None:
        kwargs = _parse_kwargs(args)
        search = (kwargs.get("search") or "").strip().lower()

        if search:
            self._chats_search[chat_id] = search
        else:
            self._chats_search.pop(chat_id, None)

        if not self._clients:
            await self._admin.send_text(chat_id, "No bot clients available")
            return

        all_chats = await self._collect_chats()

        if not all_chats:
            await self._admin.send_text(chat_id, "No accessible chats found")
            return

        if search:
            all_chats = [c for c in all_chats if search in c.title.lower()]

        if not all_chats:
            if search:
                await self._admin.send_text(chat_id, f'No chats matching "{search}"')
            else:
                await self._admin.send_text(chat_id, "No accessible chats found")
            return

        await self._render_chats_page(chat_id, all_chats, page=0, search=search)

    async def _render_chats_page(
        self,
        chat_id: int,
        all_chats: list[ChatInfo],
        page: int,
        search: str = "",
        message_id: int | None = None,
    ) -> None:
        total = len(all_chats)
        total_pages = (total + self._ITEMS_PER_PAGE - 1) // self._ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start = page * self._ITEMS_PER_PAGE
        page_chats = all_chats[start : start + self._ITEMS_PER_PAGE]

        header = "Chats"
        if search:
            header += f' matching "{search}"'
        if total_pages > 1:
            header += f" (page {page + 1}/{total_pages})"

        lines = [
            header + ":",
            f"{'Title':<30} {'ID':<15} {'Type':<12} {'Members':>8}  Ex",
        ]
        for c in page_chats:
            export_mark = "✅" if c.exportable else "❌"
            lines.append(
                f"{c.title[:28]:<30} {c.chat_id:<15} {c.chat_type.value:<12} "
                f"{c.members:>8}  {export_mark}"
            )
        lines.append("")
        lines.append(f"Total: {total} chat{'s' if total != 1 else ''}")

        buttons: list[list[dict[str, str]]] = []
        if total_pages > 1:
            nav_row: list[dict[str, str]] = []
            if page > 0:
                nav_row.append({"text": "◀️ Prev", "callback_data": f"chats:{page - 1}"})
            nav_row.append(
                {"text": f"{page + 1}/{total_pages}", "callback_data": "chats:noop"}
            )
            if page < total_pages - 1:
                nav_row.append({"text": "Next ▶️", "callback_data": f"chats:{page + 1}"})
            buttons.append(nav_row)

        text = "\n".join(lines)

        if message_id is not None:
            await self._admin.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=buttons,
            )
        else:
            await self._admin.send_text(
                chat_id,
                text,
                reply_markup=buttons,
            )

    async def handle_chats_callback(self, event: CallbackQueryEvent) -> None:
        try:
            page = int(event.callback_data.split(":", 1)[1])
        except (ValueError, IndexError):
            await self._admin.answer_callback_query(event.callback_id)
            return

        search = self._chats_search.get(event.chat_id, "")

        all_chats = await self._collect_chats()
        if not all_chats:
            await self._admin.answer_callback_query(
                event.callback_id, "No chats available"
            )
            return

        if search:
            all_chats = [c for c in all_chats if search in c.title.lower()]

        if not all_chats:
            await self._admin.answer_callback_query(
                event.callback_id, "No matching chats"
            )
            return

        await self._render_chats_page(
            event.chat_id,
            all_chats,
            page=page,
            search=search,
            message_id=event.message_id,
        )
        await self._admin.answer_callback_query(event.callback_id)

    async def cmd_export(self, chat_id: int, args: list[str]) -> None:
        if self._chat_exporter is None:
            await self._admin.send_text(chat_id, "Export service not available")
            return

        if not args:
            await self._admin.send_text(
                chat_id,
                "Usage: /export <chat_id> [--since <date|msg_id>] [--offset <msg_id>] [--parallelism N]",
            )
            return

        kwargs = _parse_kwargs(args)
        positional = [a for a in args if not a.startswith("--")]

        if not positional:
            await self._admin.send_text(chat_id, "Missing chat_id argument")
            return

        try:
            target_chat_id = int(positional[0])
        except ValueError:
            await self._admin.send_text(chat_id, f"Invalid chat_id: {positional[0]}")
            return

        since: str | int | None = None
        since_str = kwargs.get("since")
        if since_str:
            if since_str.lstrip("-").isdigit():
                since = int(since_str)
            else:
                since = str(since_str)

        parallelism = 1
        par_str = kwargs.get("parallelism")
        if par_str:
            try:
                parallelism = max(1, int(par_str))
            except ValueError:
                await self._admin.send_text(
                    chat_id, f"Invalid parallelism value: {par_str}"
                )
                return

        offset: int | None = None
        offset_str = kwargs.get("offset")
        if offset_str:
            try:
                offset = int(offset_str)
            except ValueError:
                await self._admin.send_text(
                    chat_id, f"Invalid offset value: {offset_str}"
                )
                return

        if self._chat_exporter.state not in (ExportState.IDLE,):
            await self._admin.send_text(
                chat_id,
                f"Export already in progress (state: {self._chat_exporter.state.value})",
            )
            return

        await self._admin.send_text(
            chat_id,
            f"Starting export of chat {target_chat_id}...",
        )

        asyncio.ensure_future(
            self._chat_exporter.export_chat(
                chat_id=target_chat_id,
                notify_chat_id=chat_id,
                since=since,
                parallelism=parallelism,
                offset=offset,
            )
        )

    async def cmd_export_cancel(self, chat_id: int) -> None:
        if self._chat_exporter is None:
            await self._admin.send_text(chat_id, "Export service not available")
            return
        if self._chat_exporter.state != ExportState.RUNNING:
            await self._admin.send_text(chat_id, "No export is currently running")
            return
        self._chat_exporter.cancel()
        await self._admin.send_text(chat_id, "Export cancelled")

    async def handle_export_callback(self, event: CallbackQueryEvent) -> None:
        if self._chat_exporter is None:
            return
        action = event.callback_data
        if action == "export:pause":
            self._chat_exporter.pause()
            await self._admin.answer_callback_query(event.callback_id, "Export paused")
        elif action == "export:resume":
            self._chat_exporter.resume()
            await self._admin.answer_callback_query(event.callback_id, "Export resumed")
        elif action == "export:cancel":
            self._chat_exporter.cancel()
            await self._admin.answer_callback_query(
                event.callback_id, "Export cancelled"
            )
        else:
            await self._admin.answer_callback_query(event.callback_id)
