# Changelog

## [Unreleased]

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
