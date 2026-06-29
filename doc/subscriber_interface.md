# Subscriber Interface

This doc describes how subscriber services interact with tg-if via RabbitMQ (AMQP).

## Overview

tg-if uses two exchanges:

| Exchange | Type | Direction |
|----------|------|-----------|
| `tg-if.events` | topic | tg-if publishes → subscribers consume |
| `tg-if.responses` | direct | subscribers publish → tg-if consumes |

Subscribers **create their own queues** bound to `tg-if.events` with routing key patterns (e.g., `incoming.events.aibot.#`). tg-if never creates subscriber queues.

On `tg-if.responses`, tg-if declares and consumes from three queues detailed below.

---

## Incoming Events (`tg-if.events`)

**Purpose:** tg-if publishes Telegram events here. Subscribers create queues and bind with routing key patterns to receive the events they need.

**Exchange:** `tg-if.events` (topic, durable)

### Routing Key Pattern

```text
incoming.events.{bot_name}.{event_type}.{subtype}
```

### Envelope

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

### Callback Events

When `event_type` is `"callback_query"`, the envelope includes three additional top-level fields for responding:

| Field | Type | Description |
|-------|------|-------------|
| `callback_id` | string | Telegram callback query ID — used as `callback_query_id` in `answer_callback_query` |
| `callback_data` | string | Data attached to the inline button |
| `message_id` | integer | Message ID of the button message — used in `edit_message_text` |

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440001",
  "timestamp": 1706543215.456,
  "bot_id": "aibot",
  "event_type": "callback_query",
  "event_subtype": "text",
  "chat_id": 12345,
  "user_id": 67890,
  "routing_context": {
    "chat_type": "private"
  },
  "callback_id": "cb_99",
  "callback_data": "option_1",
  "message_id": 42,
  "payload": {}
}
```

---

## 1. `outgoing.responses`

**Purpose:** Subscribers send reply messages to Telegram.

**Queue:** `outgoing.responses` — durable, bound with routing key `"response"`

### Envelope

```json
{
  "response_id": "660e8400-e29b-41d4-a716-446655440001",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1706543215.456,
  "bot_id": "aibot",
  "chat_id": 12345,
  "response_type": "text",
  "payload": { ... },
  "reply_to": "amq.gen-my-reply-queue"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `reply_to` | string (optional) | Queue name for delivery result notification. See [Delivery Results](#delivery-results) below. |

### Supported Response Types

`response_type` maps to a Pyrofork method. `payload` keys become the method's kwargs.

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

### Callback Query Flow

Inline button interactions involve two responses:

1. Subscriber receives a `callback_query` event with `callback_id`, `callback_data`, `message_id`, `chat_id` as top-level fields
2. Subscriber publishes `answer_callback_query` using `callback_id` as `callback_query_id` to show a toast notification
3. Subscriber publishes `edit_message_text` using `message_id` and `chat_id` to update the button message

```json
[
  {
    "response_type": "answer_callback_query",
    "payload": { "callback_query_id": "cq_99", "text": "Processing...", "show_alert": false }
  },
  {
    "response_type": "edit_message_text",
    "chat_id": 12345,
    "payload": { "message_id": 42, "text": "Done!" }
  }
]
```

### Delivery Results

If the request includes `reply_to`, tg-if publishes a delivery status to that queue (via the default exchange).

| Field | Type | Description |
|-------|------|-------------|
| `response_id` | string | Echoes the original `response_id` |
| `correlation_id` | string | Echoes the original `correlation_id` |
| `bot_id` | string | Echoes the original `bot_id` |
| `chat_id` | integer | Echoes the original `chat_id` |
| `status` | string | `"delivered"` or `"failed"` |
| `error_type` | string (optional) | Telegram error identifier, e.g. `"USER_IS_BLOCKED"`, `"CHAT_WRITE_FORBIDDEN"`, `"PEER_ID_INVALID"`; absent on success |
| `error_message` | string (optional) | Full error description; absent on success |
| `timestamp` | string (ISO-8601) | When the result was produced |

```json
{
  "response_id": "660e8400-e29b-41d4-a716-446655440001",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "bot_id": "aibot",
  "chat_id": 12345,
  "status": "failed",
  "error_type": "USER_IS_BLOCKED",
  "error_message": "Telegram says: [400 USER_IS_BLOCKED] ... The user blocked you",
  "timestamp": "2025-01-01T00:00:01.234"
}
```

Terminal delivery errors (`reply_to` or not) are silently dropped if the broker connection is unavailable — tg-if logs a warning but does not retry.

---

## 1.1 Media File Upload

For files larger than ~16 MB — or when the subscriber prefers not to inline binary data in AMQP messages — tg-if supports a two-step upload flow:

1. **POST /upload/{bot_id}** — upload the file via HTTP multipart
2. **OutgoingResponse** — reference the file via `upl_<SHA256>` in the payload

tg-if resolves `upl_<hash>` at send time: if a Telegram `file_id` is already cached it uses it directly (fast path); otherwise it sends the bytes via Pyrofork and caches the returned `file_id` for reuse.

See the full protocol spec (Español): [`doc/subscriber_media_interface_esp.md`](subscriber_media_interface_esp.md)

### Supported key types

Any file-typed payload key works with `upl_<hash>`:

- `photo`, `video`, `document`, `audio`
- `media` items inside `media_group`

Non-`upl_` values pass through unchanged — mixed usage is supported (e.g. `document: "upl_abc", thumb: "file_id_xyz"`).

### Admin commands

Use these via the admin bot:

| Command | Purpose |
|---------|---------|
| `/upload-list [--bot B]` | List upload records |
| `/upload-prune --older-than Nd [--bot B] [--keep-first N] [--max-size M]` | Prune old records matching criteria |
| `/upload-purge [--confirm] [--bot B]` | Purge all upload data |

---

## 2. `media-config`

**Purpose:** Subscribers set media download policies (eager vs lazy caching) per scope.

**Queue:** `media-config` — durable, bound with routing key `"media-config"`

### Message

```json
{
  "scope": "user",
  "scope_id": "12345",
  "content_types": ["photo", "video"],
  "action": "eager"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `scope` | string | `"global"`, `"chat"`, or `"user"` |
| `scope_id` | string | `chat_id` or `user_id` (null for global) |
| `content_types` | list | Media types, or `["all"]` |
| `action` | string | `"eager"` (download immediately) or `"lazy"` (download on first access) |

Precedence: user > chat > global. Last-added rule wins at same scope.

---

## 3. `subscriber-commands`

**Purpose:** Subscribers register bot commands for Telegram's bot command menu. Messages are processed once at startup — tg-if merges registrations across all subscribers and calls `set_bot_commands` on the Telegram client.

**Queue:** `subscriber-commands` — durable, bound with routing key `"subscriber-commands"`

### Request — Register

```json
{
  "action": "register",
  "bot_id": "aibot",
  "subscriber_id": "svc_1",
  "commands": [
    { "command": "start", "description": "Start the bot" },
    { "command": "help", "description": "Show help" }
  ],
  "reply_to": "amq.gen-abc123"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | `"register"` or `"deregister"` |
| `bot_id` | string | Which bot to register commands for |
| `subscriber_id` | string | Your unique identifier |
| `commands` | list | `[{command, description}, ...]` |
| `reply_to` | string | Queue name for the response (optional) |

### Request — Deregister

```json
{
  "action": "deregister",
  "bot_id": "aibot",
  "subscriber_id": "svc_1",
  "reply_to": "amq.gen-abc123"
}
```

### Response

Published to the `reply_to` queue via the default exchange:

```json
{
  "status": "ok",
  "registered": ["start", "help"],
  "conflicts": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` or `"nok"` |
| `registered` | list | Command names that were registered/removed |
| `conflicts` | list | Conflict details if status is `"nok"` |

On conflict (same command name registered by another subscriber):

```json
{
  "status": "nok",
  "registered": [],
  "conflicts": [
    "command 'start' already registered by subscriber 'svc_2'"
  ]
}
```
