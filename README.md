# tg-if

Telegram API Receiver service that connects multiple Telegram accounts via MTProto (Pyrofork), receives events, routes them through a rules engine, and publishes to RabbitMQ Streams for processing by subscriber services.

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
│         RabbitMQ Streams                       │
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

## 🚀 Configuration

### Environment Variables

```bash
cp .env.example .env
```

```bash
# RabbitMQ Configuration
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# Service Configuration
LOG_LEVEL=INFO
HEALTH_CHECK_PORT=8080
```

### Bot Configuration (`config/bots.yaml`)

```yaml
bots:
  - name: aibot
    api_id: 12345
    api_hash: "your_api_hash_here"
    session_file: ./sessions/aibot.session
    routing_rules:
      - condition:
          event_type: command
          command_starts_with: /admin
        target: incoming.events.aibot.commands.admin
      
      - condition:
          event_type: message
          has_media: true
          media_type: photo
        target: incoming.events.aibot.messages.image
      
      - condition:
          event_type: message
          has_media: false
        target: incoming.events.aibot.messages.text
      
      - condition:
          event_type: callback_query
        target: incoming.events.aibot.callbacks
      
      - condition: {}  # default fallback
        target: incoming.events.aibot.unhandled

  - name: supportbot
    api_id: 67890
    api_hash: "another_api_hash"
    session_file: ./sessions/supportbot.session
    routing_rules:
      - condition:
          event_type: command
        target: incoming.events.supportbot.commands
      
      - condition:
          event_type: message
        target: incoming.events.supportbot.messages
```

## ▶️ Execution

```bash
# Install dependencies
uv sync

# Run service
python src/main.py
```

On first run, interactive login will be requested for each bot (phone number + code). Sessions are saved in `sessions/` for subsequent runs.

## 🧠 Broker Streams

| Stream Pattern | Direction | Description |
| -------------- | --------- | ----------- |
| `incoming.events.{bot}.commands.*` | Published | Command events (e.g., /start, /help) |
| `incoming.events.{bot}.messages.*` | Published | Regular messages (text, media) |
| `incoming.events.{bot}.callbacks.*` | Published | Inline button callbacks |
| `incoming.events.{bot}.unhandled` | Published | Events not matching any rule |
| `outgoing.responses` | Consumed | Responses to send to Telegram |

**Direction Legend:**

- **Published**: tg-if publishes to this stream (subscribers consume)
- **Consumed**: tg-if consumes from this stream (subscribers publish)

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
- **RabbitMQ Streams**: Message broker with ordering guarantees
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
├── version.txt
├── uv.lock
├── pyproject.toml
├── .python-version
├── .env.example
│
├── config/
│   ├── bots.yaml              # Bot configurations and routing rules
│   └── bots.example.yaml
│
├── sessions/                  # MTProto sessions (runtime, gitignored)
│
├── src/
│   ├── __init__.py
│   ├── main.py                # Application entrypoint
│   │
│   ├── app/                   # Application layer
│   │   ├── __init__.py
│   │   ├── admin_commands.py      # Admin bot interactive command handler
│   │   ├── admin_notifier.py      # Admin bot notification dispatcher
│   │   ├── log_buffer.py          # In-memory ring buffer for structlog
│   │   ├── metrics.py             # Producer-consumer metrics counters
│   │   ├── receiver_service.py    # Orchestrates sessions and event loop
│   │   ├── event_dispatcher.py    # Rules engine and routing logic
│   │   └── response_consumer.py   # Consumes outgoing responses
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
│       ├── metrics_exporter.py  # Prometheus metric definitions
│       ├── telegram/
│       │   ├── __init__.py
│       │   ├── client.py      # Pyrofork client wrapper
│       │   └── handlers.py    # Telegram event handlers
│       └── broker/
│           ├── __init__.py
│           ├── rabbitmq.py    # RabbitMQ Streams client
│           ├── publisher.py   # Message publishing
│           └── consumer.py    # Response consumer
│
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_admin_commands.py
    │   ├── test_admin_notifier.py
    │   ├── test_consumer_retry.py
    │   ├── test_event_dispatcher.py
    │   ├── test_metrics.py
    │   ├── test_response_consumer.py
    │   └── test_rules_engine.py
    ├── integration/
    │   ├── __init__.py
    │   ├── test_telegram_flow.py
    │   └── test_broker_flow.py
    └── fixtures/
        ├── __init__.py
        └── sample_events.json
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
  "sessions": {
    "aibot": "connected",
    "supportbot": "connected"
  },
  "broker": "connected",
  "uptime_seconds": 3600
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

Health is checked every 60 seconds. Notifications are sent on state transitions only (no repeated alerts for stable states).

### Interactive Commands

DM the admin bot to execute commands:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/status` | Service status with connection states and producer-consumer metrics |
| `/bots` | List configured bots and rule counts |
| `/rules --bot <name>` | Show routing rules for a specific bot (omit `--bot` for all) |
| `/log [count]` | Show recent log entries (default 20) |

Example `/status` output:

```text
📊 Service Status  |  uptime: 2h 15m

Connections:
  broker       ✅
  aibot        ✅
  supportbot   ✅
  admin        ✅

Incoming events:
  aibot       recv: 142 → match: 138 → publish: 138
  supportbot  recv: 89  → match: 85  → publish: 85

Outgoing responses:
  consumed: 203 → sent: 200 → failed: 3
```

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

# Run container
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

# Run tests
uv run pytest

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/

# Format code
uv run ruff format src/

# Install pre-commit hooks (ruff via Docker, mypy on host)
pre-commit install
```
