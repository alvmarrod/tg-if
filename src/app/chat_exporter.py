from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import structlog

from domain.entities import ExportProgress, ExportState
from infrastructure.config import AppConfig
from infrastructure.telegram.client import TelegramClient

logger = structlog.get_logger()


def _monthly_filename(timestamp: datetime) -> str:
    return f"{timestamp.year}-{timestamp.month:02d}.json"


def _media_subdir(media_type: str) -> str:
    mapping: dict[str, str] = {
        "photo": "photo",
        "video": "video",
        "video_note": "video",
        "animation": "animation",
        "audio": "audio",
        "voice": "audio",
        "document": "document",
        "sticker": "sticker",
    }
    return mapping.get(media_type, "other")


def _media_extension(msg: Any) -> str:
    """Resolve file extension from a Pyrogram Message media attribute."""
    if msg.photo:
        return ".jpg"
    for attr_name in ("document", "video", "audio", "animation", "sticker"):
        attr = getattr(msg, attr_name, None)
        if attr is None:
            continue
        if attr.mime_type:
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
                "video/mp4": ".mp4",
                "video/webm": ".webm",
                "audio/mpeg": ".mp3",
                "audio/ogg": ".ogg",
                "audio/mp4": ".m4a",
            }
            return ext_map.get(attr.mime_type, f".{attr.mime_type.split('/')[-1]}")
        if attr.file_name and "." in attr.file_name:
            return f".{attr.file_name.rsplit('.', 1)[-1]}"
    return ".bin"


def _extract_media_info(msg: Any) -> dict[str, Any] | None:
    """Extract media metadata from a Pyrogram Message."""
    media_types = [
        ("photo", msg.photo),
        ("video", msg.video),
        ("audio", msg.audio),
        ("document", msg.document),
        ("animation", msg.animation),
        ("sticker", msg.sticker),
        ("video_note", msg.video_note),
        ("voice", msg.voice),
    ]
    for mtype, media in media_types:
        if media is None:
            continue
        info: dict[str, Any] = {
            "type": mtype,
            "file_unique_id": getattr(media, "file_unique_id", None),
            "file_id": getattr(media, "file_id", None),
            "file_size": getattr(media, "file_size", 0),
        }
        if hasattr(media, "width") and getattr(media, "width", None) is not None:
            info["width"] = media.width
            info["height"] = media.height
        if hasattr(media, "duration"):
            info["duration"] = getattr(media, "duration", None)
        return info
    return None


def _extract_reactions(msg: Any) -> list[dict[str, Any]] | None:
    """Extract aggregate reactions from a Pyrogram Message."""
    if not hasattr(msg, "reactions") or msg.reactions is None:
        return None
    reactions = []
    for r in msg.reactions.reactions:
        reactions.append({"emoji": r.emoji, "count": r.count})
    return reactions if reactions else None


def _serialize_message(msg: Any, media_rel_path: str | None = None) -> dict[str, Any]:
    """Serialize a Pyrogram Message to the export JSON dict."""
    out: dict[str, Any] = {
        "message_id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
        "from_user": {
            "id": msg.from_user.id if msg.from_user else None,
            "is_bot": msg.from_user.is_bot if msg.from_user else None,
            "first_name": msg.from_user.first_name if msg.from_user else None,
            "last_name": msg.from_user.last_name if msg.from_user else None,
            "username": msg.from_user.username if msg.from_user else None,
            "language_code": getattr(msg.from_user, "language_code", None),
        }
        if msg.from_user
        else None,
        "text": msg.text or msg.caption or None,
        "caption": msg.caption or None,
    }

    media_info = _extract_media_info(msg)
    if media_info:
        media_info["local_path"] = media_rel_path
        out["media"] = media_info

    reactions = _extract_reactions(msg)
    if reactions:
        out["reactions"] = reactions

    out["reply_to_message_id"] = msg.reply_to_message_id
    fwd = msg.forward_origin
    out["is_forward"] = fwd is not None
    sender = getattr(fwd, "sender_user", None) if fwd else None
    out["forward_from"] = (
        {
            "id": sender.id,
            "first_name": sender.first_name,
            "last_name": sender.last_name,
            "username": sender.username,
        }
        if sender
        else None
    )
    out["forward_date"] = fwd.date.isoformat() if fwd and fwd.date else None

    return out


class ChatExportEngine:
    """Orchestrates on-demand chat history exports.

    Only one export can run at a time. Supports pause, resume, and cancel
    via asyncio primitives. Progress is reported by editing an admin
    progress message with an inline keyboard.
    """

    def __init__(
        self,
        config: AppConfig,
        clients: Mapping[str, TelegramClient],
        admin_client: TelegramClient | None = None,
        user_client: TelegramClient | None = None,
    ) -> None:
        self._export_path = Path(config.export_storage_path)
        self._clients = clients
        self._admin = admin_client
        self._user_client = user_client

        self._lock = asyncio.Lock()
        self._paused = asyncio.Event()
        self._paused.set()  # not paused default
        self._cancelled = asyncio.Event()

        self._progress = ExportProgress()
        self._progress_msg_id: int | None = None
        self._progress_chat_id: int | None = None

        self._seen_file_ids: set[str] = set()

    @property
    def state(self) -> ExportState:
        return self._progress.state

    @property
    def progress(self) -> ExportProgress:
        return self._progress

    def pause(self) -> None:
        if self._progress.state != ExportState.RUNNING:
            return
        self._paused.clear()
        self._progress.state = ExportState.PAUSED

    def resume(self) -> None:
        if self._progress.state != ExportState.PAUSED:
            return
        self._paused.set()
        self._progress.state = ExportState.RUNNING

    def cancel(self) -> None:
        self._cancelled.set()
        self._progress.state = ExportState.CANCELLED

    async def export_chat(
        self,
        chat_id: int,
        notify_chat_id: int | None = None,
        since: str | int | None = None,
        parallelism: int = 1,
    ) -> None:
        """Run a full chat export.

        chat_id is the target chat to export. notify_chat_id is where
        progress messages are sent (the admin's private chat).

        Acquires the export lock. Returns early if:
        - Lock is held (another export running)
        - No user client configured or cannot access the chat
        - Cancelled during export
        """
        if self._lock.locked():
            msg = "Export already in progress"
            logger.warning(msg)
            raise RuntimeError(msg)

        async with self._lock:
            self._cancelled.clear()
            self._paused.set()
            self._seen_file_ids.clear()
            self._progress = ExportProgress(
                state=ExportState.RUNNING,
                current_chat_id=chat_id,
                start_time=datetime.now(timezone.utc),
            )
            self._progress_msg_id = None
            self._progress_chat_id = None

            try:
                client = await self._user_client_for_export(chat_id)
                logger.info("export access verified", chat_id=chat_id)

                since_msg_id: int | None = None
                since_date: datetime | None = None
                if isinstance(since, int):
                    since_msg_id = since
                elif isinstance(since, str):
                    if since.isdigit() or (
                        since.startswith("-") and since[1:].isdigit()
                    ):
                        since_msg_id = int(since)
                    else:
                        since_date = datetime.fromisoformat(since).replace(
                            tzinfo=timezone.utc
                        )

                bot_name = self._find_bot_name(client)

                await self._send_progress_message(
                    notify_chat_id if notify_chat_id is not None else chat_id
                )

                self._progress.total = 0

                _export_start = time.monotonic()
                logger.info(
                    "export started",
                    chat_id=chat_id,
                    since=since_msg_id
                    or (since_date.isoformat() if since_date else None),
                    parallelism=parallelism,
                )

                await self._export_messages(
                    client, chat_id, bot_name, since_msg_id, since_date, parallelism
                )

                await self._write_summary(chat_id, bot_name, since_msg_id, since_date)

                _export_elapsed = time.monotonic() - _export_start
                state = self._progress.state
                if state == ExportState.CANCELLED:
                    await self._edit_progress_message("⏹️ Export cancelled")
                else:
                    self._progress.state = ExportState.IDLE
                    st = self._progress.start_time or datetime.now(timezone.utc)
                    dur = datetime.now(timezone.utc) - st
                    summary = (
                        f"✅ Export complete — chat {chat_id}\n"
                        f"   {self._progress.processed} messages"
                    )
                    if self._progress.media_count:
                        summary += f" · {self._progress.media_count} media files"
                    summary += f" · {dur.total_seconds():.0f}s"
                    await self._edit_progress_message(summary)
                logger.info(
                    "export completed",
                    chat_id=chat_id,
                    processed=self._progress.processed,
                    media_count=self._progress.media_count,
                    duration_s=round(_export_elapsed, 1),
                )

            except Exception:
                logger.exception("Export failed", chat_id=chat_id)
                self._progress.state = ExportState.IDLE
                await self._edit_progress_message("❌ Export failed")
                raise
            finally:
                self._progress.state = ExportState.IDLE

    async def _resolve_client(self, chat_id: int) -> TelegramClient | None:
        """Find a bot client that has seen this chat via known_chats.

        Returns None if no bot client knows this chat.
        Does NOT probe get_chat_history (bots cannot use it).
        """
        for client in self._clients.values():
            for d in client.known_chats:
                if d["chat_id"] == chat_id:
                    return client
        return None

    async def _user_client_for_export(self, chat_id: int) -> TelegramClient:
        """Require a user client for chat export.

        Raises RuntimeError if no user client is configured or
        the user account cannot access the chat.
        """
        if self._user_client is None:
            raise RuntimeError(
                "Chat export requires a user account (not a bot). "
                "Add a 'user' section to bots.json and "
                "run tools/auth_user.py to create the session."
            )
        try:
            await self._user_client.get_chat_history(chat_id, limit=1)
        except Exception as exc:
            raise RuntimeError(
                f"User client cannot access chat {chat_id}: {exc}"
            ) from exc
        return self._user_client

    def _find_bot_name(self, client: TelegramClient) -> str:
        if self._user_client is not None and client is self._user_client:
            return "__user__"
        for name, c in self._clients.items():
            if c is client:
                return name
        return "unknown"

    async def _send_progress_message(self, chat_id: int) -> None:
        if self._admin is None:
            return
        msg = await self._admin.send_text(
            chat_id=chat_id,
            text="⏳ Starting export...",
        )
        self._progress_msg_id = msg.id
        self._progress_chat_id = chat_id

    async def _edit_progress_message(self, text: str) -> None:
        if (
            self._admin is None
            or self._progress_msg_id is None
            or self._progress_chat_id is None
        ):
            return
        try:
            await self._admin.edit_message_text(
                chat_id=self._progress_chat_id,
                message_id=self._progress_msg_id,
                text=text,
            )
        except Exception:
            logger.warning("Failed to edit progress message")

    async def _update_progress(
        self, processed: int, media_count: int = 0, media_bytes: int = 0
    ) -> None:
        self._progress.processed = processed
        self._progress.media_count = media_count
        self._progress.media_bytes = media_bytes

        text = f"📦 {processed} messages"
        if media_count:
            text += f" · {media_count} media"
        await self._edit_progress_message(text)

    async def _export_messages(
        self,
        client: TelegramClient,
        chat_id: int,
        bot_name: str,
        since_msg_id: int | None,
        since_date: datetime | None,
        parallelism: int,
    ) -> None:
        """Second pass: iterate, serialize, download media, write JSONL."""
        export_dir = self._export_path / str(chat_id)
        export_dir.mkdir(parents=True, exist_ok=True)

        media_dir = export_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        semaphore = asyncio.Semaphore(parallelism)
        open_files: dict[str, Any] = {}

        processed = 0
        media_count = 0
        media_bytes = 0

        offset_id = 0
        while True:
            if self._cancelled.is_set():
                return
            await self._paused.wait()

            page = await client.get_chat_history(
                chat_id, limit=100, offset_id=offset_id
            )
            if not page:
                break

            for msg in page:
                if self._cancelled.is_set():
                    return

                if since_msg_id is not None and msg.id < since_msg_id:
                    continue
                if since_date and msg.date and msg.date < since_date:
                    continue

                media_rel_path: str | None = None
                media_info = _extract_media_info(msg)
                if media_info and media_info.get("file_unique_id"):
                    fid = media_info["file_unique_id"]
                    subdir = _media_subdir(media_info["type"])
                    ext = _media_extension(msg)

                    subdir_path = media_dir / subdir
                    subdir_path.mkdir(parents=True, exist_ok=True)

                    media_rel_path = f"media/{subdir}/{fid}{ext}"

                    if fid not in self._seen_file_ids:
                        self._seen_file_ids.add(fid)
                        fpath = str(subdir_path / f"{fid}{ext}")

                        async def _download(
                            _msg: Any = msg,
                            _path: str = fpath,
                        ) -> tuple[int, int] | None:
                            async with semaphore:
                                try:
                                    result = await client.download_media(
                                        message=_msg, file_path=_path
                                    )
                                    if result:
                                        size = os.path.getsize(result)
                                        return 1, size
                                except Exception:
                                    logger.warning(
                                        "Media download failed",
                                        file_unique_id=fid,
                                    )
                                return None

                        dl_result = await _download()
                        if dl_result:
                            media_count += dl_result[0]
                            media_bytes += dl_result[1]

                serialized = _serialize_message(msg, media_rel_path)
                ts = msg.date or datetime.now(timezone.utc)
                monthly = _monthly_filename(ts)

                if monthly not in open_files:
                    fh = open(export_dir / monthly, "a", encoding="utf-8")
                    open_files[monthly] = fh

                open_files[monthly].write(
                    json.dumps(serialized, ensure_ascii=False) + "\n"
                )

                processed += 1
                if processed % 50 == 0:
                    await self._update_progress(processed, media_count, media_bytes)
                if processed % 1000 == 0:
                    logger.info(
                        "export progress",
                        chat_id=chat_id,
                        processed=processed,
                        media_count=media_count,
                        media_bytes=media_bytes,
                    )

            offset_id = page[-1].id

        for fh in open_files.values():
            fh.close()

        self._progress.processed = processed
        self._progress.media_count = media_count
        self._progress.media_bytes = media_bytes

    async def _write_summary(
        self,
        chat_id: int,
        bot_name: str,
        since_msg_id: int | None,
        since_date: datetime | None,
    ) -> None:
        export_dir = self._export_path / str(chat_id)
        export_dir.mkdir(parents=True, exist_ok=True)

        message_count = self._progress.processed

        monthly_files: list[str] = sorted(
            p.name
            for p in export_dir.iterdir()
            if p.suffix == ".json" and p.name != "_summary.json"
        )

        summary: dict[str, Any] = {
            "chat_id": chat_id,
            "bot_id": bot_name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "message_count": message_count,
            "media_count": self._progress.media_count,
            "media_total_bytes": self._progress.media_bytes,
            "since_message_id": since_msg_id,
            "since_date": since_date.isoformat()
            if isinstance(since_date, datetime)
            else since_date,
            "files": monthly_files,
        }

        summary_path = export_dir / "_summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
