from __future__ import annotations

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

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

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

    def get_by_hash(self, content_hash: str) -> UploadEntry | None:
        conn = self._ensure_conn()
        cur = conn.execute(
            "SELECT * FROM uploads WHERE content_hash = ?", (content_hash,)
        )
        row = cur.fetchone()
        return self._row_to_entry(row) if row else None

    def get_by_url_hash(self, url_hash: str) -> UploadEntry | None:
        conn = self._ensure_conn()
        cur = conn.execute("SELECT * FROM uploads WHERE url_hash = ?", (url_hash,))
        row = cur.fetchone()
        return self._row_to_entry(row) if row else None

    def register(self, entry: UploadEntry) -> None:
        conn = self._ensure_conn()
        now = time.time()
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

    def update_file_id(
        self, content_hash: str, file_id: str, file_unique_id: str
    ) -> None:
        conn = self._ensure_conn()
        now = time.time()
        conn.execute(
            """UPDATE uploads
               SET file_id = ?, file_unique_id = ?,
                   last_used_at = ?, use_count = use_count + 1
               WHERE content_hash = ?""",
            (file_id, file_unique_id, now, content_hash),
        )
        conn.commit()

    def touch_usage(self, content_hash: str) -> None:
        conn = self._ensure_conn()
        now = time.time()
        conn.execute(
            """UPDATE uploads
               SET last_used_at = ?, use_count = use_count + 1
               WHERE content_hash = ?""",
            (now, content_hash),
        )
        conn.commit()

    def list_all(self, bot_id: str | None = None) -> list[UploadEntry]:
        conn = self._ensure_conn()
        if bot_id:
            cur = conn.execute(
                "SELECT * FROM uploads WHERE bot_id = ? ORDER BY last_used_at DESC",
                (bot_id,),
            )
        else:
            cur = conn.execute("SELECT * FROM uploads ORDER BY last_used_at DESC")
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def delete(self, content_hash: str) -> bool:
        conn = self._ensure_conn()
        cur = conn.execute(
            "DELETE FROM uploads WHERE content_hash = ?", (content_hash,)
        )
        conn.commit()
        return cur.rowcount > 0

    def purge_all(self) -> int:
        conn = self._ensure_conn()
        cur = conn.execute("DELETE FROM uploads")
        conn.commit()
        return cur.rowcount
