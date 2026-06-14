# Changelog

## [Unreleased]

### Added

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

### Changed

- Migrated from RabbitMQ Streams to regular AMQP for lighter resource usage
- Pydantic `Config` → `model_config = ConfigDict(...)` (deprecation fix)
- Replaced `datetime.utcnow()` → `datetime.now(timezone.utc)`
- Pre-commit markdownlint switched from file inclusion to `.venv` exclusion
- Design docs moved from root into `doc/` directory
- Client health monitoring upgraded from 60s polling to instant callbacks
