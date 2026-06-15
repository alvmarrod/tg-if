from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass
class FileInfo:
    bot_id: str
    file_unique_id: str
    ext: str
    size: int
    accesses: int
    last_access: datetime | None
    stored_at: datetime


_EXT_MIME: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "ogg": "audio/ogg",
    "mp3": "audio/mpeg",
    "bin": "application/octet-stream",
}


def mime_for_ext(ext: str) -> str:
    return _EXT_MIME.get(ext, "application/octet-stream")


class MediaStorage(Protocol):
    async def store(
        self, bot_id: str, file_unique_id: str, data: bytes, ext: str
    ) -> str: ...

    async def retrieve(self, bot_id: str, file_unique_id: str) -> bytes | None: ...

    async def path_for(self, bot_id: str, file_unique_id: str) -> Path | None: ...

    async def delete(self, bot_id: str, file_unique_id: str) -> bool: ...

    async def list_files(self, bot_id: str | None = None) -> list[FileInfo]: ...

    async def stats(self) -> dict[str, Any]: ...

    async def prune(
        self,
        *,
        keep_first: int | None = None,
        max_size: int | None = None,
        older_than_days: int | None = None,
    ) -> int: ...

    async def purge(self) -> int: ...


class DiskStorage:
    def __init__(self, base_path: str = "/data/media") -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._accesses: dict[str, int] = {}
        self._last_access: dict[str, float] = {}
        self._stored_at: dict[str, float] = {}

    def _key(self, bot_id: str, file_unique_id: str) -> str:
        return f"{bot_id}/{file_unique_id}"

    def _path_for(self, bot_id: str, file_unique_id: str) -> Path:
        return self._base / bot_id / file_unique_id

    async def store(
        self, bot_id: str, file_unique_id: str, data: bytes, ext: str
    ) -> str:
        dir_path = self._base / bot_id
        dir_path.mkdir(parents=True, exist_ok=True)

        # Strip any existing extension — use the provided ext
        file_path = dir_path / f"{file_unique_id}.{ext}"
        # Avoid duplicate writes: check if path already exists
        if not file_path.exists():
            file_path.write_bytes(data)

        k = self._key(bot_id, file_unique_id)
        if k not in self._stored_at:
            self._stored_at[k] = time.time()
        self._touch_access(k)
        return str(file_path)

    async def retrieve(self, bot_id: str, file_unique_id: str) -> bytes | None:
        # Search for any extension
        dir_path = self._base / bot_id
        if not dir_path.exists():
            return None
        for f in dir_path.iterdir():
            if f.stem == file_unique_id and f.is_file():
                k = self._key(bot_id, file_unique_id)
                self._touch_access(k)
                return f.read_bytes()
        return None

    async def path_for(self, bot_id: str, file_unique_id: str) -> Path | None:
        dir_path = self._base / bot_id
        if not dir_path.exists():
            return None
        for f in dir_path.iterdir():
            if f.stem == file_unique_id and f.is_file():
                return f
        return None

    async def delete(self, bot_id: str, file_unique_id: str) -> bool:
        path = await self.path_for(bot_id, file_unique_id)
        if path is None:
            return False
        path.unlink()
        k = self._key(bot_id, file_unique_id)
        self._accesses.pop(k, None)
        self._last_access.pop(k, None)
        self._stored_at.pop(k, None)
        return True

    async def list_files(self, bot_id: str | None = None) -> list[FileInfo]:
        results: list[FileInfo] = []
        bots = (
            [bot_id] if bot_id else [d.name for d in self._base.iterdir() if d.is_dir()]
        )
        for bid in bots:
            dir_path = self._base / bid
            if not dir_path.exists():
                continue
            for f in dir_path.iterdir():
                if not f.is_file():
                    continue
                fid = f.stem
                ext = f.suffix.lstrip(".")
                k = self._key(bid, fid)
                results.append(
                    FileInfo(
                        bot_id=bid,
                        file_unique_id=fid,
                        ext=ext,
                        size=f.stat().st_size,
                        accesses=self._accesses.get(k, 0),
                        last_access=(
                            datetime.fromtimestamp(
                                self._last_access[k], tz=timezone.utc
                            )
                            if k in self._last_access
                            else None
                        ),
                        stored_at=datetime.fromtimestamp(
                            self._stored_at.get(k, f.stat().st_mtime), tz=timezone.utc
                        ),
                    )
                )
        return results

    async def stats(self) -> dict[str, Any]:
        files = await self.list_files()
        total_size = sum(f.size for f in files)
        by_type: dict[str, int] = {}
        type_size: dict[str, int] = {}
        for f in files:
            by_type[f.ext] = by_type.get(f.ext, 0) + 1
            type_size[f.ext] = type_size.get(f.ext, 0) + f.size
        return {
            "total_files": len(files),
            "total_size_bytes": total_size,
            "by_type": {
                ext: {"count": by_type[ext], "size_bytes": type_size[ext]}
                for ext in by_type
            },
        }

    async def prune(
        self,
        *,
        keep_first: int | None = None,
        max_size: int | None = None,
        older_than_days: int | None = None,
    ) -> int:
        files = await self.list_files()
        if not files:
            return 0

        if older_than_days is not None:
            cutoff = time.time() - older_than_days * 86400
            deleted = 0
            for f in files:
                if f.stored_at.timestamp() < cutoff:
                    if await self.delete(f.bot_id, f.file_unique_id):
                        deleted += 1
            return deleted

        if keep_first is not None or max_size is not None:
            sorted_files = sorted(
                files,
                key=lambda f: (
                    f.accesses,
                    f.last_access.timestamp() if f.last_access else 0,
                ),
                reverse=True,
            )
            if max_size is not None:
                total = sum(f.size for f in files)
                to_prune: list[FileInfo] = []
                for f in reversed(sorted_files):
                    if total <= max_size:
                        break
                    to_prune.append(f)
                    total -= f.size
                sorted_files = to_prune
            elif keep_first is not None:
                sorted_files = sorted_files[keep_first:]

            deleted = 0
            for f in sorted_files:
                if await self.delete(f.bot_id, f.file_unique_id):
                    deleted += 1
            return deleted

        return 0

    async def purge(self) -> int:
        files = await self.list_files()
        deleted = 0
        for f in files:
            if await self.delete(f.bot_id, f.file_unique_id):
                deleted += 1
        return deleted

    def _touch_access(self, key: str) -> None:
        self._accesses[key] = self._accesses.get(key, 0) + 1
        self._last_access[key] = time.time()
