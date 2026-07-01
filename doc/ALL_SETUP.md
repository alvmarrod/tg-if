# Telegram Bot Microservices Architecture

> **Note:** This document reflects early design (RabbitMQ Streams era). Current architecture is documented in `doc/architecture_overview.md` and subsystem docs (`doc/subsystems/*.md`). Media retrieval design: `doc/media_retrieval.md`.

## System Overview

A scalable microservices architecture for building advanced Telegram bots with decoupled business logic. The system uses Pyrofork for direct MTProto API access, RabbitMQ Streams for message ordering, and independent subscriber services for feature implementation.

**Key Principles:**

- Services are stateless or manage their own state
- Message ordering preserved per chat
- Multiple bots supported from single API Receiver
- Subscribers implement specific features/capabilities

---

## Architecture Diagram

```text
[ Telegram Servers ]
        │
        ▼
┌────────────────────────────────────────────────┐
│         API Receiver (Pyrofork)                │
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
│  │ - Read from outgoing.responses         │   │
│  │ - Match bot session                    │   │
│  │ - Send to Telegram via Pyrofork        │   │
│  └────────────────────────────────────────┘   │
└────────────────────────────────────────────────┘
        │                              ▲
        │ Publish                      │ Consume
        ▼                              │
┌────────────────────────────────────────────────┐
│         RabbitMQ Streams                       │
│                                                 │
│  Streams:                                      │
│  • incoming.events.{bot}.{type}.{subtype}     │
│  • outgoing.responses                          │
│                                                 │
│  Features:                                     │
│  • Per-chat ordering (partition: chat_id)     │
│  • Persistent streams                          │
│  • Dead letter queues                          │
└────────────────────────────────────────────────┘
        │
        │ Subscribe
        ▼
┌────────────────────────────────────────────────┐
│         Subscriber Services (N)                │
│                                                 │
│  ┌──────────────┐  ┌──────────────┐           │
│  │ Subscriber 1 │  │ Subscriber 2 │    ...    │
│  │              │  │              │           │
│  │ Feature A    │  │ Feature B    │           │
│  │ Own State    │  │ Own State    │           │
│  │ Own Storage  │  │ Own Storage  │           │
│  └──────────────┘  └──────────────┘           │
│         │                  │                   │
│         └──────────────────┘                   │
│                    │                           │
│         Publish responses back                 │
│                    ▼                           │
│         outgoing.responses                     │
└────────────────────────────────────────────────┘
```

---

## Components

### 1. API Receiver

**Responsibilities:**

- Maintain Pyrofork sessions for multiple bots
- Receive updates from Telegram servers
- Apply routing rules to determine target stream
- Extract metadata for routing decisions
- Consume response messages and send to Telegram

**Subcomponents:**

**Session Manager:**

- Stores authentication tokens per bot
- Manages multiple concurrent Pyrofork client instances
- Handles reconnection and health checks

**Event Dispatcher:**

- Receives raw Telegram updates
- Applies rules engine based on configuration
- Enriches messages with routing metadata
- Publishes to appropriate RabbitMQ stream

**Response Consumer:**

- Subscribes to `outgoing.responses` stream
- Matches `bot_id` to active session
- Executes Telegram API calls via Pyrofork
- Handles rate limiting and retries

### 2. Message Queue Broker (RabbitMQ Streams)

**Configuration:**

- RabbitMQ 3.9+ with Streams enabled
- Streams partitioned by `chat_id` for ordering
- Persistent storage for durability

**Stream Topics:**

Incoming events follow hierarchical pattern:

```text
incoming.events.{bot_name}.{event_type}.{subtype}
```

Examples:

- `incoming.events.supportbot.commands.admin`
- `incoming.events.aibot.messages.text`
- `incoming.events.aibot.messages.image`
- `incoming.events.salesbot.callbacks.product`
- `incoming.events.aibot.edited_message.text`

Outgoing responses:

```text
outgoing.responses
```

### 3. Subscriber Services

**Characteristics:**

- Stateless or self-managed state
- Each subscriber handles specific features
- Independent deployment and scaling
- Own database/storage if needed

**Operation:**

- Subscribe to relevant stream topics
- Process incoming events
- Publish responses to `outgoing.responses`
- Handle own errors and logging

---

## Message Formats

### Incoming Event Envelope

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1706543210.123,
  "bot_id": "aibot",
  "event_type": "command",
  "event_subtype": "text",
  "chat_id": 12345,
  "user_id": 67890,
  "message_id": 100,
  "text": "/start",
  "caption": null,
  "command_args": [],
  "from_user": {
    "id": 67890,
    "is_bot": false,
    "first_name": "John",
    "last_name": null,
    "username": "john_doe",
    "language_code": "en"
  },
  "reply_to_message_id": null,
  "routing_context": {
    "chat_type": "private",
    "command": "start",
    "has_media": false,
    "user_role": null
  },
  "payload": {}
}
```

### Outgoing Response Envelope

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
    "reply_markup": {
      // Optional keyboard/buttons
    }
  }
}
```

---

## Routing Configuration

API Receiver uses a rules engine with configuration per bot:

```yaml
bots:
  - name: aibot
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

  - name: supportbot
    session_file: ./sessions/supportbot.session
    routing_rules:
      # ... rules for supportbot
```

**Rule Evaluation:**

1. Rules evaluated top to bottom
2. First matching rule determines target stream
3. If no match, route to default stream: `incoming.events.{bot_name}.unhandled`

---

## Data Flow

### Incoming Message Flow

1. **Telegram → API Receiver**: Update received via Pyrofork
2. **Event Dispatcher**:
   - Extract bot context
   - Apply routing rules
   - Enrich with metadata
   - Generate event envelope
3. **Publish to RabbitMQ**: Event sent to target stream with `chat_id` partition key
4. **RabbitMQ**: Routes to appropriate stream, maintains ordering per chat
5. **Subscriber Consumes**: Service processes event
6. **Subscriber Responds**: Publishes response to `outgoing.responses`
7. **Response Consumer**: Reads response, matches bot session
8. **API Receiver → Telegram**: Sends response via Pyrofork

### Ordering Guarantee

- **Partition key**: `chat_id`
- All messages from same chat go to same stream partition
- Single consumer per partition ensures FIFO processing
- Timestamp used for sorting within partition

---

## Error Handling

### Dead Letter Queue (DLQ)

- Failed events after max retries sent to DLQ
- DLQ streams: `dlq.incoming.events`, `dlq.outgoing.responses`
- Manual inspection and replay capability

### Subscriber Errors

- Subscribers catch exceptions locally
- Log error details to monitoring system
- Optionally publish error message to user
- Do not propagate failures to broker

### API Receiver Errors

- Telegram API errors (rate limit, flood wait) trigger automatic backoff
- Failed sends after retries logged and alerted
- Session disconnections trigger reconnection logic

---

## Deployment

### API Receiver

- Single deployment per environment
- Manages all bot sessions
- Vertical scaling for additional bots
- Health endpoint exposes session status

### RabbitMQ

- Cluster for high availability
- Persistent streams configuration
- Monitoring via management plugin

### Subscribers

- Independent deployments
- Horizontal scaling per subscriber
- Deploy/update without affecting other services
- Each subscriber can use different tech stack

---

## Technology Stack

- **API Receiver**: Python with Pyrofork
- **Message Broker**: RabbitMQ 3.9+ (Streams)
- **Subscribers**: Any language with RabbitMQ client
- **Message Format**: JSON
- **Configuration**: YAML for routing rules
