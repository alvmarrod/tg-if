# tg-if — Agent Reference

## Project Identity

**tg-if** is a Telegram MTProto gateway service that receives events via Pyrofork, routes them through a rules engine, and publishes to RabbitMQ (AMQP) for subscriber consumption. Also consumes responses from `outgoing.responses` and sends them to Telegram.

The core distinction vs. the Bot HTTP API: Pyrofork (MTProto) bypasses Bot API limitations (rate limits, webhook-only, no access to full chat history, restricted media handling) by speaking the Telegram protocol directly.

## Current State

| Layer | File | Status |
|-------|------|--------|
| Domain entities | `src/domain/entities.py` | Implemented (Pydantic models — OutgoingResponse, BotCommandRegistration, SubscriberCommandEnvelope) |
| Domain schemas | `src/domain/schemas.py` | Populated (FileInfo, AdminSignalType) |
| Domain rules | `src/domain/rules.py` | Implemented (RulesEngine, RoutingRule) |
| App event_dispatcher | `src/app/event_dispatcher.py` | Implemented |
| App receiver_service | `src/app/receiver_service.py` | Implemented (orchestrator) |
| App response_consumer | `src/app/response_consumer.py` | Implemented (8 response types) |
| App bot_command_registry | `src/app/bot_command_registry.py` | Implemented |
| App subscriber_command_handler | `src/app/subscriber_command_handler.py` | Implemented |
| Infra config | `src/infrastructure/config.py` | Implemented |
| Infra health | `src/infrastructure/health.py` | Implemented (includes client status) |
| Infra telegram/client.py | `src/infrastructure/telegram/client.py` | Implemented (8 send methods) |
| Infra telegram/handlers.py | `src/infrastructure/telegram/handlers.py` | Implemented |
| Infra broker/* | `src/infrastructure/broker/*` | Implemented (RabbitMQManager, Publisher, Consumer w/ retry + routing_key) |
| Tests | `tests/*` | 210 unit / 7 integration |
| Config files | `config/bots.json` | Populated (gitignored) |
| Config files | `.env.example` | Populated |
| Subscriber interface | `doc/subscriber_interface.md` | Created |
| RabbitMQ setup | `doc/rabbitmq_setup.md` | Updated (links to subscriber_interface.md) |
| Monitor commands | `doc/monitor_cmds.md` | Created |
| Media retrieval design | `doc/media_retrieval.md` | Approved |
| Media retrieval roadmap | `.agent/media-retrieval-roadmap.md` | — |
| Dockerfile | `Dockerfile` | Multi-stage build (339MB) |
| Makefile | `Makefile` | Implemented |
| Entrypoint | `main.py` | Implemented (async, ReceiverService) |

## Architecture Summary

See `README.md` for full diagram. Key flow:

```text
Telegram --(MTProto)--> tg-if --(RabbitMQ AMQP)--> Subscribers
                           ^                             |
                           |-- outgoing.responses <-------|
                           |                             |
                           |-- GET /files/ (media fetch) -|
                               (HTTP, not AMQP)
```

Media retrieval design: `doc/media_retrieval.md` — hybrid eager/lazy cache layer with on-demand HTTP proxy.

### AMQP Topology

```text
Exchange: tg-if.events (topic, durable)
  Routing keys: incoming.events.{bot}.{type}.{subtype}
  Each subscriber creates its own queue bound to this exchange
  with a pattern (e.g. incoming.events.aibot.#) — pub/sub model.

Exchange: tg-if.responses (direct, durable)
  Queue: outgoing.responses (bound with key "response")
  Queue: media-config (bound with key "media-config")
  Queue: subscriber-commands (bound with key "subscriber-commands")
  All bindings handled by Consumer via routing_key parameter (not in rabbitmq.py).
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
| Hybrid eager/lazy media retrieval (`doc/media_retrieval.md`) | Immediate event publication + write-through HTTP cache; config controls timing of first download only; avoids blocking on download |
| Queue bindings delegated to Consumer via `routing_key` parameter | Single source of truth at wiring layer, not in rabbitmq.py |
| Subscriber commands channel is for bot command registration only | Not for routing rules or admin-plane access |
| Topology for subscribers documented in `doc/subscriber_interface.md` | Separate from internal subsystem docs |

## Implementation Roadmap

Per `doc/media_retrieval.md`: implementation deferred; see doc for full design.

Per `doc/Hybrid approach.md` (legacy):

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
