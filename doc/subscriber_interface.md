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

All events share these top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | UUID v4 identifying this event |
| `timestamp` | float | Unix timestamp of when the envelope was built |
| `bot_id` | string | Bot that received the event |
| `event_type` | string | `"message"`, `"command"`, `"callback_query"`, `"edited_message"` |
| `event_subtype` | string or null | `"text"`, `"photo"`, `"video"`, `"audio"`, `"document"`, or `null` |
| `chat_id` | integer | Telegram chat ID |
| `user_id` | integer | Telegram user ID of the sender |
| `message_id` | integer or null | Telegram message ID (null for callback queries without a message) |
| `text` | string or null | Full message text (commands and text messages); `null` for callback queries |
| `caption` | string or null | Media caption; `null` for non-media messages |
| `command_args` | array of strings or null | Arguments after the command; `null` for non-command events |
| `from_user` | object or null | Sender info: `id`, `is_bot`, `first_name`, `last_name`, `username`, `language_code` |
| `reply_to_message_id` | integer or null | The message ID this event is replying to; `null` if not a reply |
| `reply_to_message` | object or null | The replied-to message: `message_id`, `from` (user dict), `text`, `caption`; `null` if not a reply |
| `routing_context` | object | Context used for routing decisions (chat_type, command, has_media, media_type, user_role, is_reply, is_forward) |
| `payload` | object | Raw Telegram data (file metadata for media; `{}` for text/commands) |

Conditional fields:

| Field | Condition |
|-------|-----------|
| `file_id` | Present when the event carries a media file |
| `file_unique_id` | Present when the event carries a media file |
| `media_status` | Present when the event carries a media file |
| `media_url` | Present when the event carries a media file |
| `callback_id` | Present when `event_type` is `"callback_query"` |
| `callback_data` | Present when `event_type` is `"callback_query"` |

Example:

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
  "reply_to_message": null,
  "routing_context": {
    "chat_type": "private",
    "command": "start",
    "has_media": false,
    "user_role": null
  },
  "payload": {}
}
```

### Edited Message Events

When `event_type` is `"edited_message"`, the envelope carries the same fields as a regular message or command, but reflects the **updated** content after a user edited their message. Edited commands include `command`, `command_args`, and `text`. Edited media (e.g., a photo caption change) includes `file_id`, `file_unique_id`, `media_type`, etc.

The routing key pattern is:

```text
incoming.events.{bot_name}.edited_message.{subtype}
```

Example (edited command):

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440002",
  "timestamp": 1706543220.789,
  "bot_id": "aibot",
  "event_type": "edited_message",
  "event_subtype": "text",
  "chat_id": 12345,
  "user_id": 67890,
  "message_id": 100,
  "text": "/start help",
  "caption": null,
  "command_args": ["help"],
  "from_user": {
    "id": 67890,
    "is_bot": false,
    "first_name": "John",
    "last_name": null,
    "username": "john_doe",
    "language_code": "en"
  },
  "reply_to_message_id": null,
  "reply_to_message": null,
  "routing_context": {
    "chat_type": "private",
    "command": "start",
    "has_media": false,
    "user_role": null
  },
  "payload": {}
}
```

### Callback Events

When `event_type` is `"callback_query"`, the envelope includes two additional top-level fields for responding:

| Field | Type | Description |
|-------|------|-------------|
| `callback_id` | string | Telegram callback query ID — used as `callback_query_id` in `answer_callback_query` |
| `callback_data` | string | Data attached to the inline button |
| `message_id` | integer | Message ID of the button message — used in `edit_message_text` (also present in base envelope as `null` for non-message types) |

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440001",
  "timestamp": 1706543215.456,
  "bot_id": "aibot",
  "event_type": "callback_query",
  "event_subtype": "text",
  "chat_id": 12345,
  "user_id": 67890,
  "message_id": 42,
  "text": null,
  "caption": null,
  "command_args": null,
  "from_user": {
    "id": 67890,
    "is_bot": false,
    "first_name": "John",
    "last_name": null,
    "username": "john_doe",
    "language_code": "en"
  },
  "reply_to_message_id": null,
  "reply_to_message": null,
  "routing_context": {
    "chat_type": "private"
  },
  "callback_id": "cb_99",
  "callback_data": "option_1",
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

`response_type` maps to a PyroTGFork method. `payload` keys become the method's kwargs.

| `response_type` | Required payload keys | Optional payload keys (common) | Notes |
|----------------|----------------------|-------------------------------|-------|
| `text` | `text` | `parse_mode`, `reply_to_message_id`, `reply_markup` | Any PyroTGFork `send_message` kwarg is accepted (e.g. `disable_web_page_preview`, `disable_notification`, `protect_content`) |
| `photo` | `photo` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | Any PyroTGFork `send_photo` kwarg is accepted |
| `video` | `video` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | Any PyroTGFork `send_video` kwarg is accepted |
| `document` | `document` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | Any PyroTGFork `send_document` kwarg is accepted |
| `audio` | `audio` | `caption`, `parse_mode`, `reply_to_message_id`, `reply_markup` | Any PyroTGFork `send_audio` kwarg is accepted |
| `media_group` | `media` (list of `{type, media, caption?}`) | `reply_to_message_id` | Any PyroTGFork `send_media_group` kwarg is accepted |
| `edit_message_text` | `message_id`, `text` | `parse_mode`, `reply_markup` | Edits an existing message; any PyroTGFork `edit_message_text` kwarg is accepted |
| `answer_callback_query` | `callback_query_id` | `text`, `show_alert`, `url`, `cache_time` | `chat_id` is **not forwarded**; any PyroTGFork `answer_callback_query` kwarg is accepted |
| `delete_message` | `message_ids` (int or list[int]) | `revoke` | Calls `delete_messages` on PyroTGFork. `chat_id` is forwarded automatically. |

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

tg-if resolves `upl_<hash>` at send time: if a Telegram `file_id` is already cached it uses it directly (fast path); otherwise it sends the bytes via PyroTGFork and caches the returned `file_id` for reuse.

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
