# Media Retrieval — Implementation Roadmap

**Date:** 2026-06-15  
**Design doc:** `doc/media_retrieval.md`  

## Dependency Graph

```text
Phase 1 (Handlers + Entities)
  ├──► Phase 2 (HTTP endpoint + Disk cache)
  ├──► Phase 3 (Config system)
  │     └──► Phase 4 (Eager download)
  │           └──► Phase 6 (Status updates, optional)
  └──► Phase 5 (Storage mgmt commands)
```

---

## Phase 1 — Handler Extraction + Domain Entities

**Goal:** Events carry file IDs so subscribers can fetch media and tg-if can serve it.

### Files to modify

**`src/domain/entities.py`**

- Add `file_id: str | None = None` to `MessageEvent`
- Add `file_unique_id: str | None = None` to `MessageEvent`
- Add `media_status: str = "pending"` to `MessageEvent` (always `"pending"` on first publish; `"ready"` after eager download)
- Add `media_url: str | None = None` to `MessageEvent` (populated at publish time)

**`src/infrastructure/telegram/handlers.py`**

- In `message_to_event()`, extract `file_id` and `file_unique_id` from the appropriate media attribute on the Pyrofork `Message` object (photo, video, audio, document, animation, voice, video_note, sticker)
- Populate `raw_payload` with media metadata: `mime_type`, `size`, `file_name`, `width`, `height`, `duration`
- Determine extension by media type for `media_url` construction

---

## Phase 2 — HTTP Endpoint + Disk Cache

**Goal:** Subscribers can fetch media via `GET /files/{bot_id}/{file_unique_id}`. Lazy mode functional.

### New files

**`src/infrastructure/media/__init__.py`**

- Package init

**`src/infrastructure/media/cache.py`**

- `class DiskCache` — methods:
  - `store(bot_id, file_unique_id, data: bytes, ext: str) -> Path`
  - `retrieve(bot_id, file_unique_id) -> bytes | None`
  - `path_for(bot_id, file_unique_id) -> Path`
  - In-memory counters: `accesses` dict, `last_access` dict (persisted to disk optionally via JSON sidecar)
  - `list_files(bot_id=None) -> list[FileInfo]` — returns all cached files with metadata
  - `stats() -> dict` — aggregate by type
  - `prune(keep_first=None, max_size=None, older_than=None) -> int` — delete matching files
  - `purge() -> int` — delete all

**`src/infrastructure/media/endpoint.py`**

- `async def handle_file_get(request: web.Request) -> web.Response`:
  1. Extract `bot_id` and `file_unique_id` from route params
  2. Look up `TelegramClient` by `bot_id` from request app
  3. Check `DiskCache.retrieve()` — if hit, stream with `Content-Type` derived from extension
  4. If miss, call `client._client.download_media(file_id, in_memory=True)`, stream response, write-through to cache asynchronously
  5. Handle errors: 404 (bot/file not found), 502 (Telegram download failed), 503 (client disconnected)

### Files to modify

**`src/infrastructure/health.py`**

- Import and register `GET /files/{bot_id}/{file_id}` route
- Accept `clients` dict and `cache` instance in `create_health_server()`

**`src/app/receiver_service.py`**

- Instantiate `DiskCache` with configurable base path (env var `MEDIA_CACHE_PATH` or default `/data/media`)
- Pass `cache` and `clients` to `create_health_server()`

---

## Phase 3 — Media Config System

**Goal:** Dynamic eager/lazy rules managed via admin commands and AMQP.

### New files

**`src/domain/entities.py`** (add entities)

- `MediaScope(str, Enum)`: `GLOBAL`, `CHAT`, `USER`
- `MediaConfigRule`:
  - `scope: MediaScope`
  - `scope_id: str | None = None` — chat_id or user_id; `None` for global
  - `content_types: list[str]` — e.g. `["gif"]`, `["gif", "image", "audio"]`; `"all"` means all types
  - `action: str` — `"eager"` or `"lazy"`

**`src/app/media_config.py`**

- `class MediaConfigManager`:
  - In-memory rule list
  - `evaluate(bot_id, chat_id, user_id, media_type) -> bool` — applies precedence: user > chat > content_type > global default (which is `lazy`)
  - `add_rule(rule: MediaConfigRule)` — inserts at correct precedence position
  - `remove_rule(scope, scope_id, content_types)`
  - `list_rules() -> list[MediaConfigRule]`
  - Optionally persist rules to JSON on each change and reload on startup

### Files to modify

**`src/app/admin_commands.py`**

- Add 3 new command handlers wired to `MediaConfigManager`:
  - `/media-eager --scope global|chat:<id>|user:<id> --type gif,image,...`
  - `/media-lazy --scope ... --type ...`
  - `/media-config` — show current rules

**`src/infrastructure/broker/rabbitmq.py`**

- In `connect()`, declare queue `media-config` and bind to `tg-if.responses` with routing key `"media-config"`

**`src/app/receiver_service.py`**

- Instantiate `MediaConfigManager`
- Create a second `Consumer` for the `media-config` queue with a callback that parses the message and calls `MediaConfigManager.add_rule()` / `remove_rule()`
- Wire `MediaConfigManager` into `AdminCommandHandler`

---

## Phase 4 — Eager Download Background Task

**Goal:** Config-matched media is downloaded proactively on event receipt without blocking publication.

### New files

**`src/app/media_downloader.py`**

- `class MediaDownloader`:
  - `__init__(cache: DiskCache, config: MediaConfigManager, clients: dict[str, TelegramClient], publisher: Publisher)`
  - `async def on_event(event: MessageEvent)` — called after event is dispatched:
    1. If no `file_id` or no `file_unique_id`, return (no media to download)
    2. Call `config.evaluate(event.bot_id, event.chat_id, event.user_id, event.media_type)`
    3. If lazy, return
    4. If eager: fire async task via `asyncio.create_task(self._download(event))`
  - `async def _download(event: MessageEvent)`:
    1. Check if `file_unique_id` already cached (dedup) — skip if yes
    2. Get client: `self._clients[event.bot_id]`
    3. Download: `client._client.download_media(event.file_id, in_memory=True)`
    4. Store: `self._cache.store(event.bot_id, event.file_unique_id, data, ext)`
    5. If status updates enabled: publish `media_ready` event

### Files to modify

**`src/app/receiver_service.py`**

- In `_on_event()`, call `media_downloader.on_event(event)` alongside `_dispatcher.dispatch()` (both non-blocking to the subscriber — dispatch publishes immediately, downloader spawns a background task)

---

## Phase 5 — Storage Management Admin Commands

**Goal:** Admin can inspect and prune the media cache.

### Files to modify (no new files)

**`src/app/admin_commands.py`**

- Add 4 new command handlers:
  - `/media-list [--sort size:asc,accesses:desc,lru:desc]` — calls `DiskCache.list_files()`, formats table
  - `/media-prune --keep first:N | --prune first:N | --max-size N | --older-than Nd` — calls `DiskCache.prune()`
  - `/media-purge` — confirm then call `DiskCache.purge()`
  - `/media-stats` — calls `DiskCache.stats()`, formats by-type breakdown
- Update `/help` to list new commands

---

## Phase 6 — Status Update Events (Optional)

**Goal:** Subscribers can listen for `media_ready` events instead of polling the HTTP endpoint.

### Files to modify

**`src/domain/entities.py`**

- Add `MediaReadyEvent(BaseModel)`:
  - `file_unique_id: str`
  - `file_id: str`
  - `media_url: str`
  - `original_event_id: str`
  - `bot_id: str`

**`src/app/media_downloader.py`**

- After successful `cache.store()` in `_download()`, publish to `tg-if.events` using `Publisher.publish()` with routing key `media.ready.{bot_id}.{media_type}` and `MediaReadyEvent` as body
- Guarded by a flag (enabled/disabled) to avoid noise if subscribers don't use it

---

## Backlog Items

Once the roadmap is approved, add these backlog items to `.agent/backlog.md`:

| ID | Title | Phase |
|----|-------|-------|
| B-101 | Handler extraction + media fields in entities | 1 |
| B-102 | Disk cache store | 2 |
| B-103 | HTTP /files/ endpoint | 2 |
| B-104 | MediaConfigManager + domain entities | 3 |
| B-105 | Config admin commands | 3 |
| B-106 | AMQP media-config consumer | 3 |
| B-107 | Eager download background task | 4 |
| B-108 | Storage management admin commands | 5 |
| B-109 | Media ready status events (optional) | 6 |
