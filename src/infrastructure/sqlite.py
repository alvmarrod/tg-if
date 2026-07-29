from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from domain.schemas import UploadEntry


class UploadRegistry:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS uploads (
        content_hash TEXT PRIMARY KEY,
        url_hash TEXT UNIQUE,
        url TEXT,
        file_id TEXT,
        file_unique_id TEXT,
        bot_id TEXT NOT NULL,
        ext TEXT NOT NULL DEFAULT 'bin',
        size INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        last_used_at REAL NOT NULL,
        use_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_uploads_bot ON uploads(bot_id);
    CREATE INDEX IF NOT EXISTS idx_uploads_url_hash ON uploads(url_hash);
    """

    def __init__(self, db_path: str = "/data/uploads.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _row_to_entry(self, row: sqlite3.Row) -> UploadEntry:
        return UploadEntry(
            content_hash=row["content_hash"],
            url_hash=row["url_hash"],
            url=row["url"],
            file_id=row["file_id"],
            file_unique_id=row["file_unique_id"],
            bot_id=row["bot_id"],
            ext=row["ext"],
            size=row["size"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            use_count=row["use_count"],
        )

    async def connect(self) -> None:
        """Connect to the database and initialize schema."""
        if self._conn is not None:
            return

        def _sync_connect() -> sqlite3.Connection:
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(self._SCHEMA)
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_sync_connect)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is None:
            return
        conn = self._conn
        self._conn = None

        await asyncio.to_thread(conn.close)

    async def get_by_hash(self, content_hash: str) -> UploadEntry | None:
        conn = await self._ensure_conn()

        def _op() -> UploadEntry | None:
            cur = conn.execute(
                "SELECT * FROM uploads WHERE content_hash = ?", (content_hash,)
            )
            row = cur.fetchone()
            return self._row_to_entry(row) if row else None

        return await asyncio.to_thread(_op)

    async def get_by_url_hash(self, url_hash: str) -> UploadEntry | None:
        conn = await self._ensure_conn()

        def _op() -> UploadEntry | None:
            cur = conn.execute("SELECT * FROM uploads WHERE url_hash = ?", (url_hash,))
            row = cur.fetchone()
            return self._row_to_entry(row) if row else None

        return await asyncio.to_thread(_op)

    async def register(self, entry: UploadEntry) -> None:
        conn = await self._ensure_conn()
        now = time.time()

        def _op() -> None:
            conn.execute(
                """
                INSERT INTO uploads
                    (content_hash, url_hash, url, bot_id, ext, size,
                     created_at, last_used_at, use_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.content_hash,
                    entry.url_hash,
                    entry.url,
                    entry.bot_id,
                    entry.ext,
                    entry.size,
                    now,
                    now,
                    0,
                ),
            )
            conn.commit()

        await asyncio.to_thread(_op)

    async def update_file_id(
        self, content_hash: str, file_id: str, file_unique_id: str
    ) -> None:
        conn = await self._ensure_conn()
        now = time.time()

        def _op() -> None:
            conn.execute(
                """UPDATE uploads
                   SET file_id = ?, file_unique_id = ?,
                       last_used_at = ?, use_count = use_count + 1
                   WHERE content_hash = ?""",
                (file_id, file_unique_id, now, content_hash),
            )
            conn.commit()

        await asyncio.to_thread(_op)

    async def touch_usage(self, content_hash: str) -> None:
        conn = await self._ensure_conn()
        now = time.time()

        def _op() -> None:
            conn.execute(
                """UPDATE uploads
                   SET last_used_at = ?, use_count = use_count + 1
                   WHERE content_hash = ?""",
                (now, content_hash),
            )
            conn.commit()

        await asyncio.to_thread(_op)

    async def list_all(self, bot_id: str | None = None) -> list[UploadEntry]:
        conn = await self._ensure_conn()

        def _op() -> list[UploadEntry]:
            if bot_id:
                cur = conn.execute(
                    "SELECT * FROM uploads WHERE bot_id = ? ORDER BY last_used_at DESC",
                    (bot_id,),
                )
            else:
                cur = conn.execute("SELECT * FROM uploads ORDER BY last_used_at DESC")
            return [r for r in (self._row_to_entry(r) for r in cur.fetchall())]

        return await asyncio.to_thread(_op)

    async def delete(self, content_hash: str) -> bool:
        conn = await self._ensure_conn()

        def _op() -> bool:
            cur = conn.execute(
                "DELETE FROM uploads WHERE content_hash = ?", (content_hash,)
            )
            conn.commit()
            return cur.rowcount > 0

        return await asyncio.to_thread(_op)

    async def purge_all(self) -> int:
        conn = await self._ensure_conn()

        def _op() -> int:
            cur = conn.execute("DELETE FROM uploads")
            conn.commit()
            return cur.rowcount

        return await asyncio.to_thread(_op)

    async def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        return self._conn
