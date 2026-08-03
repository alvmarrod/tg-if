# Changelog

## [Unreleased]

## [0.13.1] - 2026-08-03

### Fixed

- `TelegramClient.delete_message()` no longer raises a false-positive
  `RuntimeError` when Pyrogram returns a non-`None` success indicator (e.g.
  `True` in group chats). Messages are still correctly deleted.
- `DiskStorage` no longer crashes the service on `PermissionError` during
  startup when the configured base path (e.g. `/mnt/ram`) is inaccessible.
  The error is logged as a warning and all storage methods degrade safely
  until the path becomes available.
- Dockerfile: added `COPY version.txt .` to bake `version.txt` into the
  image (missing since CQ-48 in 0.13.0), preventing `FileNotFoundError` on
  startup.
- Dockerfile: added `RUN mkdir -p /mnt/ram && chown appuser:appuser /mnt/ram`
  to ensure the mount point exists and is writable in the image.
- Media metadata extraction no longer reads Pyrogram's deprecated
  `Photo.file_size` property (which logged `This property is deprecated.
  Please use sizes instead`); it now reads `sizes[-1].file_size` for
  photo-like media.
- Telegram send methods no longer pass `reply_to_message_id` to Pyrogram
  (which logged `This property is deprecated. Please use reply_parameters
  instead`); they convert it to `ReplyParameters` internally. The
  `reply_to_message_id` field in the response payload contract is unchanged.
- Added diagnostic logging in the media send path: when a payload media value
  looks like a local file path, the client logs whether the file exists on
  disk (`media source is local file` / `media source not found on disk`)
  at send time, to help diagnose missing-file send failures.

## [0.13.0] - 2026-07-30

### Changed

- CQ-48: Version is now read from `version.txt` as the single source of truth.
  Created `src/infrastructure/version.py` with a `get_version()` function that
  reads `version.txt` at runtime. `main.py` uses this instead of a hardcoded
  string. `pyproject.toml` and `version.txt` synced to `0.13.0`.
- CQ-49: `DiskStorage` constructor accepts an optional `max_tracked_files`
  parameter. See Added section below for details on LRU eviction.

### Added

- CQ-50: Added `doc/http_threat_model.md` documenting the unauthenticated HTTP
  endpoints (`/health`, `/metrics`, `/files/`, `/upload/`), their threat actors,
  and recommended deployment topology with a reverse proxy.
- CQ-51: Rate limiting on `POST /upload/` endpoint via a sliding-window
  per-IP limiter. Configured via `AppConfig.upload_rate_limit` (default 30
  requests per minute per IP, set to 0 to disable). Includes `X-Forwarded-For`
  support for reverse-proxy deployments.
- CQ-52: Session file locking via `fcntl.flock` to prevent race conditions
  during rolling deployments. `TelegramClient.start()` acquires an exclusive
  lock on `{session_file}.lock` before starting Pyrogram, and releases it on
  `stop()`. If another instance holds the lock, the second instance raises
  `RuntimeError` after a 30s timeout.
- CQ-49: Added LRU eviction to `DiskStorage` access metadata dicts
  (`_accesses`, `_last_access`, `_stored_at`). Configured via
  `AppConfig.media_max_tracked_files` (default 10000, set to 0 for unlimited).
  When the limit is exceeded, the least recently accessed entry is evicted,
  preventing unbounded memory growth from long-running services.
- CQ-45: Refactored `receiver_service.py` (499 → 402 lines) by extracting
  constructor dependency wiring into `src/app/wiring.py` (`build_components`
  function + `ServiceComponents` dataclass). `ReceiverService.__init__` now
  delegates component assembly while retaining flat attribute assignment for
  backward compatibility. Zero test changes required.
- CQ-44: Refactored `admin_commands.py` (1285 → 543 lines) by extracting
  media, upload, and export commands into three delegate classes:
  `admin_commands_media.py` (MediaCommandDelegate),
  `admin_commands_upload.py` (UploadCommandDelegate),
  `admin_commands_export.py` (ExportCommandDelegate). Shared utility
  functions moved to `admin_commands_utils.py`. `AdminCommandHandler.handle()`
  dispatches to delegates via the same command names. Zero test logic changes.

## [0.12.0] - 2026-07-29

### Changed

- CQ-39: `Publisher.publish()` now reuses a persistent AMQP channel instead of
  opening/closing a channel per message. A new `close()` method is added for
  cleanup and is called during `ReceiverService.shutdown()`. This eliminates
  the per-message channel overhead in the hot path.
- CQ-40: `DiskStorage` file I/O (`store`, `retrieve`, `delete`, `stat`) migrated
  from synchronous `pathlib` calls to `aiofiles` async open/read/write/unlink/stat,
  removing blocking I/O from the async hot path. `aiofiles` added as a core
  dependency.
- CQ-41: `UploadRegistry` SQLite operations (`connect`, `close`, `register`,
  `get_by_hash`, `list_all`, `delete`, `delete_by_bot`, `purge_all`,
  `update_file_id`, `touch_usage`) converted to async methods using
  `asyncio.to_thread`. All callers (receiver service, response consumer,
  upload routes, admin commands) updated to `await` registry calls.
- CQ-42: `_health_monitor` loop now doubles the sleep interval (60s → 120s →
  240s → max 300s) when all components are healthy, and resets to 60s
  immediately when any component is unhealthy. Reduces idle polling overhead.
- CQ-43: `_export_messages` file handles are now managed via `contextlib.ExitStack`
  instead of a manually-tracked `open_files` dict with a final close loop.
  Files are properly closed on any exit path (normal, exception, or
  `CancelledError`), preventing file descriptor leaks on cancellation.
- Code quality sweep across 33 files: type hint refinements, pre-commit hook
  alignment, mypy strict-mode compliance fixes, linting and formatting
  consistency improvements, and test corrections to match updated signatures.
  No behavioural changes.

### Fixed

- `ReceiverService.start()` no longer crashes on a single bot failure: failed
  bots are removed from `self._clients` and the rest continue; the admin
  notifier is alerted. User client failure also degrades gracefully by
  setting `self._user_client = None` instead of crashing.
- `ReceiverService.start()` now cleans up previously started consumers when a
  later consumer fails to start, preventing orphaned consumers from running.
- Added pre-commit hooks CQ-25 through CQ-31: `check-added-large-files`,
  `check-merge-conflict`, `check-json`, `check-yaml`, `check-toml`,
  `mixed-line-ending`, `trailing-whitespace`, `debug-statements`.
- CQ-32–CQ-38 CI/CD: Added CI workflow (lint, typecheck, unit tests w/ coverage
  threshold 80%, integration tests, bandit, pip-audit, Python 3.12/3.13 matrix,
  uv caching), release workflow (Docker build & push to GHCR on tag v*),
  Dependabot config (pip, GHA, Docker).
- Added `bandit`, `pip-audit`, and `hypothesis` to dev dependencies.
- CQ-24: Added `--cov=src --cov-report=term-missing` to pytest `addopts` in
  `pyproject.toml` for local coverage reporting.
- CQ-23: Added 14 property-based tests for `_match_condition` covering
  determinism, monotonicity (adding conditions never creates a match),
  per-key opposite values, media dependency, text/caption edge cases, and
  unknown-key tolerance.
- CQ-17: Added 11 unit tests for `health.py` covering `handle_health` (all
  broker/client combinations, error paths), `handle_metrics`, and
  `create_health_server` lifecycle.
- CQ-18: Added 8 unit tests for `metrics_exporter.py` covering Prometheus text
  format, all 9 expected metric names, uptime value, and counter/gauge
  behavior on separate registries.
- CQ-20: Added 2 unit tests for `main.py` covering start/stop lifecycle and
  start-failure propagation.
- CQ-22: Added 17 unit tests to `test_chat_exporter.py` covering `_media_extension`
  mime-type mapping edge cases, `_extract_media_info` for video/audio,
  `_save_checkpoint` with no current chat, corrupt checkpoint loading,
  nonexistent checkpoint deletion, `_find_bot_name` for user/unknown,
  `_resolve_client` returning None, and `_user_client_for_export` history
  failure path.
- Fixed `main.py` mypy errors (removed unused type annotation on `logger`,
  fixed `LogBuffer.processor` signature to use `MutableMapping`).
- `_on_media_config_message` no longer re-raises on validation failure: invalid
  messages are logged, admin-notified, and dropped — instead of triggering the
  consumer's retry loop for a permanently invalid message.
- Added dead-letter queue (`tg-if.dlq` exchange, `dead-letter` queue): messages
  that exceed max retries in `Consumer` are published with error metadata and
  source queue name for manual inspection, instead of being silently dropped
- `EventDispatcher.dispatch` now catches publish failures instead of letting
  the exception propagate uncaught through the Telegram event handler
- Added typed domain schemas: `FromUser`, `ReplyToMessage`, `ChatDialog`,
  `EventEnvelope`, and `MediaRawInfo` TypedDicts in `domain/schemas.py`,
  reducing `dict[str, Any]` usage from 59 to 37 sites across `src/`. Updated
  `handlers.py` constructors, `dispatcher.py` envelope builder, `client.py`
  chat registries, and `health.py` client map to use concrete types.
- Migrated all `Optional[X]` to `X | None` syntax in `domain/entities.py` (19
  fields) and `app/subscriber_command_handler.py` (1 parameter), with
  `from __future__ import annotations` added for PEP 604 compatibility
- Added `TelegramClient.download_media_in_memory()` public method so callers
  no longer access `client._client` private attribute directly (fixes
  `endpoint.py` private-attribute access, resolves CQ-09)
- Eliminated all 5 `# type: ignore` comments in `src/`: made `handle_metrics`
  async (health.py), switched `hasattr` to `isinstance` for type narrowing
  (endpoint.py), fixed `AppKey` import path (upload_routes.py), used `Any`
  typed alias for PyroTGFork internal module access (client.py), added
  `last_exc is not None` guard (consumer.py). Source tree now mypy-clean with
  zero suppressions.
- `UploadRegistry.delete()` and `purge_all()` in `sqlite.py` had unreachable
  duplicate blocks after `return` statements (dead code)
- `endpoint.py` checked `if not await storage.store(...)` against a `str` return
  value — non-empty path strings are always truthy, so the failure branch was
  never taken
- `Publisher.publish()` declared exchange `tg-if.events` as `FANOUT` instead of
  `TOPIC`, breaking topic-based routing — all published messages went to every
  bound queue regardless of routing key
- `main.py` shutdown: `asyncio.create_task(service.stop())` was scheduled
  immediately after `service.start()`, causing the service to stop right away
  regardless of signals. Signal handlers that set `stop_event` were dead code.
  Now `service.stop()` is only called after `stop_event.wait()` returns,
  so `SIGINT`/`SIGTERM` properly drive graceful shutdown.

## [0.11.0] - 2026-07-21

### Added

- `web_app` button type support in `build_reply_markup()`. Inline keyboards can
  now include `{"text": "...", "web_app": {"url": "..."}}` buttons.
- Command validation in `BotCommandRegistry.register()`: commands with uppercase
  letters or special characters are rejected with a conflict error.

### Changed

- Hyphens (`-`) in bot commands are now normalized to underscores (`_`) in both
  incoming event detection (`_detect_command`) and registry storage. Subscribers
  can register `/gb-start` and users can type `/gb-start` or `/gb_start` — both
  produce `command: "gb_start"` in the event envelope. Telegram's Bot API only
  accepts lowercase alphanumeric+underscore names, so `set_bot_commands` now
  receives the normalized form.

## [0.10.0] - 2026-07-20

### Added

- `edit_message_reply_markup` response type. Subscribers can now update only the
  inline keyboard of a message without retransmitting the text — the previously
  necessary workaround of passing the same text via `edit_message_text`.

## [0.9.5] - 2026-07-16

### Fixed

- `reaction.id` → `reaction.message_id` in `reaction_updated_to_event`. Pyrogram's
  `MessageReactionUpdated` type does not have an `.id` attribute — caused
  `AttributeError` crashes on reaction events
- Stale session recovery: when `BadMsgNotification [16]` (msg_id too low) occurs
  during client start, the stale `.session` file is now deleted and the client
  re-initialized with a fresh session — avoids permanent client failure after
  clock drifts or container restarts

## [0.9.4] - 2026-07-14

### Added

- `reply_to_message` field in incoming event envelopes. Now includes the replied-to
  message's `message_id`, `from` (user dict), `text`, and `caption` — so subscribers
  like gamification can identify who was replied to without an extra API call

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
