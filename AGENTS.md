# tg-if — Agent Reference

## Project Identity

**tg-if** is a Telegram MTProto gateway service that receives events via Pyrofork, routes them through a rules engine, and publishes to RabbitMQ (AMQP) for subscriber consumption. Also consumes responses from `outgoing.responses` and sends them to Telegram.

The core distinction vs. the Bot HTTP API: Pyrofork (MTProto) bypasses Bot API limitations (rate limits, webhook-only, no access to full chat history, restricted media handling) by speaking the Telegram protocol directly.

## Current State

| Layer | File | Status |
|-------|------|--------|
| Domain entities | `src/domain/entities.py` | Implemented (Pydantic models — OutgoingResponse) |
| Domain schemas | `src/domain/schemas.py` | Empty stub |
| Domain rules | `src/domain/rules.py` | Implemented (RulesEngine, RoutingRule) |
| App event_dispatcher | `src/app/event_dispatcher.py` | Implemented |
| App receiver_service | `src/app/receiver_service.py` | Implemented (orchestrator) |
| App response_consumer | `src/app/response_consumer.py` | Implemented |
| Infra config | `src/infrastructure/config.py` | Implemented |
| Infra health | `src/infrastructure/health.py` | Implemented (includes client status) |
| Infra telegram/client.py | `src/infrastructure/telegram/client.py` | Implemented (6 send methods) |
| Infra telegram/handlers.py | `src/infrastructure/telegram/handlers.py` | Implemented |
| Infra broker/* | `src/infrastructure/broker/*` | Implemented (RabbitMQManager, Publisher, Consumer w/ retry) |
| Tests | `tests/*` | Empty stubs |
| Config files | `config/bots.json` | Populated |
| Config files | `.env.example` | Populated |
| Dockerfile | `Dockerfile` | Empty stub |
| Makefile | `Makefile` | Empty stub |
| Entrypoint | `main.py` | Implemented (async, ReceiverService) |

## Architecture Summary

See `README.md` for full diagram. Key flow:

```
Telegram --(MTProto)--> tg-if --(RabbitMQ AMQP)--> Subscribers
                           ^                             |
                           |-- outgoing.responses <-------|
```

### AMQP Topology

```
Exchange: tg-if.events (topic, durable)
  Routing keys: incoming.events.{bot}.{type}.{subtype}
  Each subscriber creates its own queue bound to this exchange
  with a pattern (e.g. incoming.events.aibot.#) — pub/sub model.

Exchange: tg-if.responses (direct, durable)
  Queue: outgoing.responses (bound with key "response")
  Response consumer reads from this queue.
```

## Conventions

- **Language**: Python 3.14+ (`.python-version` pin; `pyproject.toml` floor `>=3.12`)
- **Package manager**: `uv` (uv.lock committed)
- **Schema layer**: Pydantic v2 (`BaseModel`, `Field`, `Config`)
- **Enums**: `str, Enum` with `use_enum_values = True`
- **Logging**: structlog (structured JSON output)
- **Testing**: pytest (directory structure exists, files pending)
- **Typing**: Full type hints, mypy strict mode
- **Linting/formatting**: ruff
- **Proto**: MTProto via Pyrofork (not HTTP Bot API)
- **Project structure**: Hexagonal-ish layout (domain/ app/ infrastructure/)
- **Config**: JSON for bot config, env vars for infrastructure settings
- **Entrypoint**: `main.py` at project root (not `src/main.py` despite README diagram)
- **Commit style**: Conventional, concise, imperative mood

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Pyrofork (MTProto) over HTTP Bot API | Bypass Bot API limitations (rate limits, webhook-only model, restricted chat access) |
| Regular RabbitMQ (AMQP) over Streams | Streams consume more server resources; regular AMQP with topic exchanges is lighter and sufficient |
| Pydantic over dataclasses | Validation, serialization, schema generation |
| Single service managing all bots | Instead of one process per bot; simpler ops, shared broker connection |
| Internal retry over NACK requeue | Transparent retry inside Consumer preserves ordering, avoids message pollution with headers |
| OutgoingResponse uses raw dict payload | Avoids premature schema pinning per response type; payload maps directly to send_* kwargs |

## Implementation Roadmap

Per `Hybrid approach.md`:

1. **Phase 1 — Foundation**: Domain data structures, config loading, basic logging (done)
2. **Phase 2 — Vertical Slice**: Single bot receive -> publish to broker -> consume response -> send to Telegram (done)
3. **Phase 3 — Expand**: Full rules engine, multiple bots, all event types, health monitoring

## Commands

- Install: `uv sync`
- Install dev: `uv sync --all-extras`
- Test: `uv run pytest`
- Type check: `uv run mypy src/`
- Lint: `uv run ruff check src/`
- Format: `uv run ruff format src/`
- Run: `python main.py`
- Pre-commit install: `pre-commit install`
- Pre-commit run all: `pre-commit run --all-files`
- Pre-commit on staged: runs automatically on `git commit`

## Repository

`/Users/btc/github/tg-if` — single initial commit `b2809b2`. License: MIT (2025 Alvaro MR).
