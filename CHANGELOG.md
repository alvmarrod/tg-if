# Changelog

## [Unreleased]

### Added

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
