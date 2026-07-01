# tg-if

Telegram MTProto gateway service that receives events via Pyrofork, routes them through a rules engine, and publishes to RabbitMQ (AMQP) for subscriber consumption. Also consumes responses from `outgoing.responses` and sends them to Telegram.

## 🧩 Architecture

```text
[ Telegram Servers ]
        │
        ▼
┌────────────────────────────────────────────────┐
│         tg-if (Pyrofork)                       │
│                                                 │
│  ┌────────────────┐  ┌────────────────────┐   │
│  │ Session        │  │ Event Dispatcher   │   │
│  │ Manager        │  │ - Rules Engine     │   │
│  │ - Auth tokens  │  │ - Topic Router     │   │
│  │ - Multi-bot    │  │ - Metadata Extract │   │
│  └────────────────┘  └────────────────────┘   │
│                                                 │
│  ┌────────────────────────────────────────┐   │
│  │ Response Consumer                       │   │
│  │ - Read outgoing.responses              │   │
│  │ - Send to Telegram                     │   │
│  └────────────────────────────────────────┘   │
└────────────────────────────────────────────────┘
        │                              ▲
        │ Publish                      │ Consume
        ▼                              │
┌────────────────────────────────────────────────┐
│         RabbitMQ (AMQP)                        │
│                                                 │
│  • incoming.events.{bot}.{type}.{subtype}     │
│  • outgoing.responses                          │
└────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────┐
│         Subscriber Services                    │
└────────────────────────────────────────────────┘
```

## ⚙️ Features

- **Multi-account support**: Manage multiple Telegram bots from one service
- **Rules-based routing**: Configure flexible routing based on message type, content, chat type, and custom conditions
- **Per-chat ordering**: Messages from the same chat are processed in order
- **Bidirectional flow**: Receive events from Telegram and send responses back
- **Session persistence**: MTProto sessions stored in `sessions/`
- **Health monitoring**: Service health and session status endpoints
- **Admin bot**: Dedicated Telegram bot for control-plane alerts and interactive commands
- **Producer-consumer metrics**: Per-bot event counters (received → matched → published) and response funnel (consumed → sent → failed)
- **Prometheus `/metrics` endpoint**: Export all counters and gauges for external scraping
- **Media retrieval**: Hybrid eager/lazy HTTP proxy for media files (see `doc/media_retrieval.md`)
- **Media upload**: Sequential HTTP upload → `upl_<hash>` reference in OutgoingResponse with Telegram file_id caching (see `doc/subscriber_media_interface_esp.md`)
- **Delete messages**: `delete_message` response type for removing messages via Pyrofork `delete_messages`
- **Edited message handling**: Subscribers receive `edited_message` events with full message context when a user edits a previously sent message (text, command, or media)
- **Enriched event envelopes**: Subscribers receive `message_id`, `text`, `caption`, `command_args`, `from_user`, and `reply_to_message_id` on every incoming event

## 🚀 Configuration

### Environment Variables

Copy and edit the example file:

```bash
cp .env.example .env
```

See [`.env.example`](.env.example) for all available variables.

### Bot Configuration

See [`config/bots.example.json`](config/bots.example.json) for a complete example with routing rules and admin bot setup. Copy it to `config/bots.json` and fill in your credentials.

## ▶️ Execution

```bash
# Install dependencies
uv sync

# Run service
python main.py
```

On first run, bots configured with `bot_token` authenticate automatically (preferred). Bots without a token require interactive login (phone number + code). Sessions are saved in `sessions/` for subsequent runs.

## 🧠 Broker Topology

| Pattern | Direction | Description |
| ------- | --------- | ----------- |
| `incoming.events.{bot}.commands.*` | Published | Command events (e.g., /start, /help) |
| `incoming.events.{bot}.messages.*` | Published | Regular messages (text, media) |
| `incoming.events.{bot}.edited_messages.*` | Published | Edited messages (text, command, media edits) |
| `incoming.events.{bot}.callbacks.*` | Published | Inline button callbacks |
| `incoming.events.{bot}.unhandled` | Published | Events not matching any rule |
| `outgoing.responses` | Consumed | Responses to send to Telegram |
| `media-config` | Consumed | Media download policy rules |
| `subscriber-commands` | Consumed | Bot command registration |

**Direction Legend:**

- **Published**: tg-if publishes to this exchange (subscribers consume)
- **Consumed**: tg-if consumes from this exchange (subscribers publish)

## 📊 Message Schemas

See [`doc/subscriber_interface.md`](doc/subscriber_interface.md) for the complete schema reference covering:

- **Incoming events** — what subscribers consume from `tg-if.events`
- **`outgoing.responses`** — all 8 supported `response_type` values with payload schemas
- **`media-config`** — media download policy rules
- **`subscriber-commands`** — bot command registration protocol

## 🔍 Routing Rules

Rules are evaluated top to bottom. First matching rule determines the target stream.

### Condition Fields

| Field | Type | Description | Example |
| ----- | ---- | ----------- | ------- |
| `event_type` | string | Type of Telegram event | `message`, `command`, `callback_query` |
| `event_subtype` | string | Subtype of event | `text`, `photo`, `video`, `document` |
| `chat_type` | string | Type of chat | `private`, `group`, `supergroup`, `channel` |
| `command` | string | Exact command match | `/start`, `/help` |
| `command_starts_with` | string | Command prefix | `/admin` |
| `has_media` | boolean | Whether message contains media | `true`, `false` |
| `media_type` | string | Type of media | `photo`, `video`, `document`, `audio` |
| `user_role` | string | User role in chat | `creator`, `administrator`, `member` |

### Target Format

Target streams follow the pattern:

```bash
incoming.events.{bot_name}.{event_type}.{subtype}
```

## 🧰 Technology Stack

- **Python 3.14+**: Core language
- **Pyrofork**: MTProto client for Telegram API
- **RabbitMQ (AMQP)**: Message broker with topic routing
- **Pydantic**: Schema validation
- **Structlog**: Structured logging
- **uv**: Fast Python package manager

## 📁 Project Structure

```bash
tg-if/
├── CHANGELOG.md
├── Dockerfile
├── LICENSE
├── Makefile
├── README.md
├── main.py                   # Application entrypoint
├── version.txt
├── uv.lock
├── pyproject.toml
├── .python-version
├── .env.example
│
├── config/
│   ├── bots.example.json     # Example bot config (commit-safe)
│   └── bots.json             # Actual bot config (gitignored, contains secrets)
│
├── sessions/                  # MTProto sessions (runtime, gitignored)
│
├── doc/                       # Design documentation
│   ├── architecture_overview.md
│   ├── media_retrieval.md
│   ├── monitor_cmds.md
│   ├── rabbitmq_setup.md
│   ├── setup_esp.md
│   ├── subscriber_interface.md
│   ├── subscriber_media_interface_esp.md    # Upload protocol spec (Español)
│   └── subsystems/
│
├── src/
│   ├── __init__.py
│   │
│   ├── app/                   # Application layer
│   │   ├── __init__.py
│   │   ├── admin_commands.py      # Admin bot interactive command handler
│   │   ├── admin_notifier.py      # Admin bot notification dispatcher
│   │   ├── log_buffer.py          # In-memory ring buffer for structlog
│   │   ├── metrics.py             # Producer-consumer metrics counters
│   │   ├── receiver_service.py    # Orchestrates sessions and event loop
│   │   ├── event_dispatcher.py    # Rules engine and routing logic
│   │   ├── response_consumer.py   # Consumes outgoing responses
│   │   ├── media_config.py        # Media config rule manager
│   │   └── media_downloader.py    # Eager media downloader
│   │
│   ├── domain/                # Domain models
│   │   ├── __init__.py
│   │   ├── entities.py        # Bot, Event, Response entities
│   │   ├── schemas.py         # Pydantic schemas for validation
│   │   └── rules.py           # Routing rule models
│   │
│   └── infrastructure/        # External integrations
│       ├── __init__.py
│       ├── config.py          # Configuration loader
│       ├── health.py          # aiohttp health/Metrics/Media server
│       ├── metrics_exporter.py  # Prometheus metric definitions
│       ├── sqlite.py          # UploadRegistry (SQLite)
│       ├── telegram/
│       │   ├── __init__.py
│       │   ├── client.py      # Pyrofork client wrapper
│       │   └── handlers.py    # Telegram event handlers
│       ├── broker/
│       │   ├── __init__.py
│       │   ├── rabbitmq.py    # RabbitMQ connection manager
│       │   ├── publisher.py   # Message publishing
│       │   └── consumer.py    # Response consumer
│       └── media/
│           ├── __init__.py
│           ├── storage.py     # Media storage (DiskStorage)
│           ├── endpoint.py    # HTTP media proxy endpoint
│           └── upload_routes.py  # POST /upload/{bot_id} endpoint
│
└── tests/
    ├── unit/                    # 20 unit test files
    ├── integration/             # 4 integration test files (opt-in, requires Docker)
    └── fixtures/                # Sample events for testing
```

## 🏥 Health Checks

Service exposes health endpoint:

```bash
GET http://localhost:8080/health
```

Response:

```json
{
  "status": "healthy",
  "broker": "connected",
  "clients": {
    "aibot": "connected",
    "supportbot": "connected"
  }
}
```

## 📈 Prometheus Metrics

Service exposes a Prometheus metrics endpoint alongside the health check:

```bash
GET http://localhost:8080/metrics
```

Returns counters and gauges in Prometheus text format (`Content-Type: text/plain; version=0.0.4`).

### Exported Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tg_if_events_received_total` | Counter | `bot` | Events received from Telegram |
| `tg_if_events_matched_total` | Counter | `bot` | Events matched by the rules engine |
| `tg_if_events_published_total` | Counter | `bot` | Events published to RabbitMQ |
| `tg_if_responses_consumed_total` | Counter | — | Responses consumed from `outgoing.responses` |
| `tg_if_responses_sent_total` | Counter | — | Responses sent to Telegram |
| `tg_if_responses_failed_total` | Counter | — | Responses that permanently failed after retries |
| `tg_if_broker_connected` | Gauge | — | Broker connection status (1/0) |
| `tg_if_client_connected` | Gauge | `bot` | Telegram client connection status (1/0) |
| `tg_if_uptime_seconds` | Gauge | — | Service uptime in seconds |

The endpoint requires no authentication — secure it via network-level access control (firewall, reverse proxy).

## 🤖 Admin Bot

A dedicated Telegram bot provides control-plane alerts and interactive management commands.

### Setup

Add an `admin` block to `config/bots.json`:

```json
{
  "admin": {
    "api_id": 99999,
    "api_hash": "your_admin_bot_hash",
    "session_file": "sessions/admin.session",
    "user_id": 123456789
  }
}
```

`user_id` is the Telegram user ID that receives notifications and can issue commands. The admin bot uses its own MTProto session (separate from event-processing bots).

### Notifications

The admin bot automatically sends alerts for control-plane events:

| Signal | Trigger |
|--------|---------|
| `⚠️ Response Failed` | A subscriber response permanently failed after max retries |
| `✅ {component} connected` | Broker or bot transitions from disconnected → connected |
| `❌ {component} disconnected` | Broker or bot transitions from connected → disconnected |

Telegram client connection changes are detected instantly via Pyrofork callbacks. Broker and admin bot status are checked every 60 seconds. Notifications are sent on state transitions only (no repeated alerts for stable states).

### Interactive Commands

DM the admin bot to execute commands:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/ping` | Liveness check |
| `/status` | Service control panel with connection states and metrics |
| `/target &lt;name&gt;` | Per-target detail (events, bots, last activity) |
| `/bots` | List configured bots and rule counts |
| `/rules [--bot &lt;name&gt;]` | Show routing rules (omit `--bot` for all) |
| `/rule-add --bot &lt;n&gt; --target &lt;key&gt; [--condition k=v ...]` | Append routing rule |
| `/rule-remove --bot &lt;n&gt; --index &lt;i&gt;` | Remove routing rule by index |
| `/log [count]` | Show recent log entries (default 20) |
| `/shutdown` | Disconnect broker and stop receivers (process stays alive) |
| `/start` | Reconnect broker and restart receivers (after `/shutdown`) |
| `/restart` | Shutdown everything and exit with code 0 (container restarts) |
| `/media-eager --scope &lt;s&gt; [--type &lt;t&gt;]` | Set eager download rule |
| `/media-lazy --scope &lt;s&gt; [--type &lt;t&gt;]` | Set lazy download rule |
| `/media-config` | List media config rules |
| `/media-list [--sort &lt;col&gt;:&lt;dir&gt;,...]` | List cached media |
| `/media-stats` | Media cache statistics |
| `/media-prune --keep-first N \| --max-size N \| --older-than Nd` | Prune media cache |
| `/media-purge [confirm]` | Delete all cached media |
| `/upload-list [--bot &lt;name&gt;]` | List upload records |
| `/upload-prune --older-than Nd [--bot &lt;name&gt;] [--keep-first N] [--max-size M]` | Prune upload cache |
| `/upload-purge [confirm] [--bot &lt;name&gt;]` | Delete all upload data |

### Lifecycle Management

The service offers three-way lifecycle control:

- **`/shutdown`**: Gracefully disconnects the broker, stops event bots, consumers, and health server. The admin bot stays running so you can issue `/start` or `/restart`. The process **does not exit**.
- **`/start`**: Reconnects the broker and re-starts all receivers. Only valid after `/shutdown`.
- **`/restart`**: Shuts down everything (same as `/shutdown`) then calls `sys.exit(0)`. In Docker, the container exits cleanly and is restarted by the orchestrator.

This allows stopping and restarting the service without losing the admin bot session or requiring a full container recycle.

### Metrics Funnel

The service tracks a producer-consumer relationship through each stage:

```text
Telegram → received → [rules engine] → matched → [publish] → published → RabbitMQ
                                                              Subscribers → responses → consumed → sent/failed
```

Each stage is independently counted per bot. These counters are also exported via the Prometheus `/metrics` endpoint for external scraping and dashboards.

## 📝 Logging

Structured JSON logs with context:

```json
{
  "timestamp": "2025-01-29T10:30:00.000Z",
  "level": "info",
  "event": "message_received",
  "bot_id": "aibot",
  "chat_id": 12345,
  "user_id": 67890,
  "event_type": "message",
  "routed_to": "incoming.events.aibot.messages.text"
}
```

## 🐳 Docker Deployment

```bash
# Build image
docker build -t tg-if:latest .

# Run container (config/bots.json must exist on the mounted volume)
docker run -d \
  --name tg-if \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/sessions:/app/sessions \
  -e RABBITMQ_HOST=rabbitmq \
  -p 8080:8080 \
  tg-if:latest
```

## 🔧 Development

```bash
# Install dependencies (including dev)
uv sync --all-extras

# Run unit tests (default, integration tests excluded)
uv run pytest

# Run integration tests (requires Docker running locally)
uv run pytest -m integration

# Run all tests (including integration)
uv run pytest -m ""

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/

# Format code
uv run ruff format src/

# Install pre-commit hooks (ruff via Docker, mypy on host)
pre-commit install
```
