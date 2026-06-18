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
| `incoming.events.{bot}.callbacks.*` | Published | Inline button callbacks |
| `incoming.events.{bot}.unhandled` | Published | Events not matching any rule |
| `outgoing.responses` | Consumed | Responses to send to Telegram |

**Direction Legend:**

- **Published**: tg-if publishes to this exchange (subscribers consume)
- **Consumed**: tg-if consumes from this exchange (subscribers publish)

## 📊 Message Schemas

### Incoming Event Schema

Published to: `incoming.events.{bot_name}.{event_type}.{subtype}`

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1706543210.123,
  "partition_key": "chat:12345",
  "bot_id": "aibot",
  "bot_name": "aibot",
  "event_type": "message",
  "event_subtype": "text",
  "chat_id": 12345,
  "user_id": 67890,
  "routing_context": {
    "chat_type": "private",
    "command": "/start",
    "has_media": false,
    "user_role": "member"
  },
  "payload": {
    "message_id": 789,
    "text": "/start",
    "date": 1706543210,
    "from": {
      "id": 67890,
      "first_name": "John",
      "username": "john_doe"
    },
    "chat": {
      "id": 12345,
      "type": "private"
    }
  }
}
```

### Outgoing Response Schema

Consumed from: `outgoing.responses`

```json
{
  "response_id": "660e8400-e29b-41d4-a716-446655440001",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1706543215.456,
  "bot_id": "aibot",
  "chat_id": 12345,
  "response_type": "text",
  "payload": {
    "text": "Hello! How can I help you?",
    "reply_to_message_id": 789,
    "parse_mode": "Markdown",
    "reply_markup": {
      "inline_keyboard": [
        [
          {"text": "Option 1", "callback_data": "opt1"},
          {"text": "Option 2", "callback_data": "opt2"}
        ]
      ]
    }
  }
}
```

#### Supported Response Types

`response_type` maps to a Pyrofork method. Payload keys become the method's kwargs.

| `response_type` | Required payload keys | Optional payload keys | Notes |
|----------------|----------------------|-----------------------|-------|
| `text` | `text` | `parse_mode`, `reply_to_message_id`, `reply_markup` | |
| `photo` | `photo` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | |
| `video` | `video` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | |
| `document` | `document` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | |
| `audio` | `audio` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | |
| `media_group` | `media` (list of `{type, media, caption?}`) | `reply_to_message_id` | |
| `edit_message_text` | `message_id`, `text` | `parse_mode`, `reply_markup` | Edits an existing message |
| `answer_callback_query` | `callback_query_id` | `text`, `show_alert`, `url`, `cache_time` | `chat_id` is **not forwarded** |

#### Callback Query Flow

A typical inline button interaction involves two responses:

1. Subscriber receives a `CallbackQueryEvent` with `callback_id`, `callback_data`, `message_id`, `chat_id`
2. Subscriber publishes `answer_callback_query` to show a toast notification
3. Subscriber publishes `edit_message_text` to update the button message

```json
[
  {
    "response_type": "answer_callback_query",
    "payload": { "callback_query_id": "cq_99", "text": "Processing...", "show_alert": false }
  },
  {
    "response_type": "edit_message_text",
    "chat_id": 12345,
    "payload": { "message_id": 42, "text": "Done! ✅" }
  }
]
```

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
│           └── endpoint.py    # HTTP media proxy endpoint
│
└── tests/
    ├── unit/                    # 13 unit test files
    ├── integration/             # 6 integration tests (opt-in, requires Docker)
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
