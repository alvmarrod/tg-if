# Changelog

## [Unreleased]

## [0.9.3] - 2026-07-14

### Fixed

- `TCP.TIMEOUT` increased from 10s to 30s to match the 15s `PING_INTERVAL`.
  Previously, socket reads timed out after 10s of inactivity, but keepalive
  pings only arrived every 15s — causing a rapid disconnect/reconnect cycle
  every ~10 seconds for all clients

## [0.9.2] - 2026-07-14

### Fixed

- `POST /upload/{bot_id}` now validates required headers before multipart
  parsing. Returns 400 with structured JSON when `Content-Type` is absent or
  wrong — instead of crashing with `KeyError`

## [0.9.1] - 2026-07-11

### Fixed

- `POST /upload/{bot_id}` returned 404 for all requests because `client_map`
  was stored under a plain string key in the health server app dict but
  retrieved via `AppKey` (different key objects in aiohttp 3.10+). Now stored
  via `ClientMapKey` AppKey, matching the handler's lookup

## [0.9.0] - 2026-07-11

### Fixed

- `send_text`, `send_photo`, `send_document`, `send_video`, `send_audio`,
  `edit_message_text`, `answer_callback_query`, `send_media_group` now accept
  `**kwargs` and forward them to the underlying Pyrogram methods. Subscriber
  extras like `disable_web_page_preview`, `disable_notification`, or
  `protect_content` are no longer rejected with `TypeError`

## [0.8.0] - 2026-07-11

### Fixed

- Debounced disconnect notifications no longer fire falsely every 5 minutes
  when the client auto-reconnects within the debounce window. A health-monitor
  poll now cancels the pending timer on reconnect detection, and
  `_disconnect_timeout` guards against sending the notification if the client
  is already connected

## [0.7.0] - 2026-07-08

### Changed

- Migrated MTProto library from Pyrofork to PyroTGFork, a community-maintained
  fork of Pyrogram with broader Telegram API support (Layer 225)
- `Connection.MAX_CONNECTION_ATTEMPTS` renamed to `MAX_RETRIES`; adapted import
  paths and type annotations for PyroTGFork compatibility

## [0.6.0] - 2026-07-08

### Changed

- Increased Pyrofork `PING_INTERVAL` to 15s, `WAIT_TIMEOUT` to 30s,
  `MAX_CONNECTION_ATTEMPTS` to 5 — reduces spurious disconnections from
  aggressive keepalive timeouts
- Debounced client disconnect admin notifications: ❌ only sent after 5 minutes
  of sustained disconnection; ✅ suppressed for transient flaps

## [0.4.0] - 2026-07-02

### Added

- User client architecture for chat export: `UserAccountConfig` model with `api_id`, `api_hash`, `session_file`; optional `user` key in `config/bots.json`; startup session-file guard with clear warning
- `TelegramClient.is_user` property and `discover_chats()` method — calls Pyrofork's real `get_dialogs()` (user-only MTProto, previously unreachable for bots)
- `ChatExportEngine._resolve_client` now probes user_client first, then falls back to bot `known_chats` registry + `get_chat_history` probe
- `/chats` command merges user_client `discover_chats()` results with bot `known_chats` when a user session is configured
- In-memory chat registry (`_register_chat`/`known_chats`) populated from all incoming event handlers (message, edited_message, callback_query, reactions), replacing broken `get_dialogs()` MTProto call for bot accounts
- Export integration test: user_client-first resolution with mocked user `get_chat_history`
- Chat export docs: user account architecture requirement, `tools/auth_user.py` session pre-auth note, `README.md` feature bullet and project tree entries
- `config/bots.example.json` user key template

### Changed

- `export_chat()` gains `notify_chat_id` parameter — progress messages now sent to admin's private chat instead of export target chat (fixes `CHANNEL_INVALID` when admin bot is not in target chat)
- `ChatType` enum expanded to 7 values matching Pyrofork: BOT, FORUM, MONOFORUM added
- `_cmd_chats` skips unknown chat types via try/except ValueError instead of crashing
- Removed unused `_find_first_client_by_dialogs` method from `ChatExportEngine`
- `can_read` in dialog output set to `True` (reading is always permitted for chat participants; no `can_read_messages` permission exists in MTProto)

### Fixed

- `get_chat_history()` no longer passes `offset_date=None` to Pyrofork when unset (caused `AttributeError: 'NoneType' has no attribute 'to_bytes'` in `Int(None.to_bytes())`)
- `get_dialogs()` replaced with `known_chats` property (Pyrofork's `messages.GetDialogs` is user-only; bots always got empty lists)
- `since_msg_id` filtered at message level in `_count_messages`/`_export_messages` (was only used as pagination offset)
- `since_date` made timezone-aware via `.replace(tzinfo=timezone.utc)`
- Export cancel test fixed: polling loop replaced with fixed sleep
- Media mock creates real temp files for integration tests

## [0.3.0] - 2026-07-01

### Added

- Chat export: `/chats` (list accessible chats), `/export` (export to monthly JSONL), `/export-cancel` commands with inline keyboard pause/resume/cancel controls and real-time progress bar
- `ChatExportEngine` — two-pass (count then export), per-message media dedup by `file_unique_id`, concurrent download via semaphore, `_summary.json` generation
- Export integration tests: 9 tests covering basic, multi-month, media dedup, reactions, pagination, `--since` (by message_id and date), cancel, summary content
- `ChatExportEngine` API: `export_chat(chat_id, since, parallelism)`, `pause()`, `resume()`, `cancel()` with single-task `asyncio.Lock`
- README badges for GitHub tag, MIT license, CI status, Ruff

### Changed

- CI pipeline: `concurrency` group cancels stale runs, removed tag triggers (no more duplicate runs), Docker job switched to `push: false` build-only smoke test; permissions moved to workflow level
- Engine type hint `dict[str, TelegramClient]` → `Mapping[str, TelegramClient]` for covariant test compatibility

### Fixed

- `_count_messages` / `_export_messages` now filter by `since_msg_id` at the message level (not just pagination offset), fixing `--since <msg_id>` behavior
- `since_date` parsed from `fromisoformat` now made timezone-aware via `.replace(tzinfo=timezone.utc)`, fixing naive/aware datetime comparison
- Export cancel test no longer hangs when engine finishes between poll cycles
- Media mock in integration tests creates real temp files so `os.path.getsize` does not raise `FileNotFoundError`
- 6 mypy errors in test files: `list`/`dict` type args, `__str__` method-assign, overlapping enum comparison, missing `answer_callback_query`, stale `ExportState` import path

## [0.2.0] - 2026-07-01

### Added

- Reaction event types: incoming event dispatcher now emits `message_reaction_updated` and `message_reaction_count_updated` events with full routing support, including `reaction_emoji` / `old_reaction_emoji` condition matching in the rules engine
- `update_type` field on `TelegramEvent` base class: each handler sets a string label (`"message"`, `"edited_message"`, `"callback_query"`, `"message_reaction_updated"`, `"message_reaction_count_updated"`) for debugging visibility
- Enhanced "no matching rule" log now includes `update_type`, `chat_id`, and `user_id`

## [0.1.0] - 2026-07-01

### Added

- `reply_to_message_id` in incoming event envelopes: subscribers now receive the original message ID when a Telegram message is a reply, restoring reply context for downstream logic
- Edited message handling: subscribers now receive `edited_message` events (text, command, media) with full envelope when a user edits a previously sent message
- Lifecycle management: `/shutdown` (disconnect broker, stop receivers, keep process alive), `/start` (reconnect and restart receivers), `/restart` (shutdown + exit with code 0 for container restart)
- `on_start` and `on_restart` callbacks to `AdminCommandHandler`
- MTProto gateway service with Pyrofork integration
- RabbitMQ AMQP pub/sub topology (tg-if.events + tg-if.responses)
- Rules engine with 10 condition fields (event type, chat type, command, media, user role)
- Admin bot with 5 interactive commands and control-plane notifications
- Per-bot event funnel counters and response funnel metrics
- Prometheus /metrics endpoint (9 counters/gauges)
- GitHub Actions CI pipeline (ruff, mypy, pytest, markdownlint, Docker)
- Docker multi-stage build (339MB final image), Makefile, pre-commit hooks
- Instant reconnect callbacks for Telegram client connection changes
- In-memory log buffer (ring buffer, 200 entries) for admin /log command
- 80 tests (76 unit + 4 integration stubs)
- Media upload system: `POST /upload/{bot_id}` endpoint, SQLite upload registry, ResponseConsumer resolution with `file_id` caching and dedup
- Admin commands: `/upload-list`, `/upload-prune`, `/upload-purge`
- Subscriber media upload interface documentation (`doc/subscriber_media_interface_esp.md`)
- 7 unit test files, 1 integration test file (upload + AMQP round-trip)
- `delete_message` response type: subscribers can remove Telegram messages via `outgoing.responses`
- Enriched event envelopes: `message_id`, `text`, `caption`, `command_args`, `from_user` (id, is_bot, first_name, last_name, username, language_code) now present on all incoming event envelopes

### Changed

- Migrated from RabbitMQ Streams to regular AMQP for lighter resource usage
- Pydantic `Config` → `model_config = ConfigDict(...)` (deprecation fix)
- Replaced `datetime.utcnow()` → `datetime.now(timezone.utc)`
- Pre-commit markdownlint switched from file inclusion to `.venv` exclusion
- Design docs moved from root into `doc/` directory
- Client health monitoring upgraded from 60s polling to instant callbacks
- MediaDownloader now respects `MediaConfigManager.evaluate()` for lazy/eager config rules (Phase 4 gap closed)
- aiohttp AppKey constants used instead of string keys (fixes NotAppKeyWarning)
- FormData test helpers always provide explicit filename (fixes DeprecationWarning)

### Fixed

- Bot command registration rejects hyphens; registered with underscores, handler accepts both
- Consumer `_run()` suppressed noisy `ChannelClosed` tracebacks during shutdown
- `ReceiverService.stop()` no longer triggers Pyrofork "Task cannot await on itself" crash
