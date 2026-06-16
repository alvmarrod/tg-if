# Domain Layer

**Location:** `src/domain/`

## Entities

- `TelegramEvent` — Incoming event from Telegram (event_type, chat_id, user_id, raw_payload, bot_id)
- `RoutingContext` — Extracted metadata for rule matching (chat_type, command, has_media, media_type, user_role, is_reply, is_forward)
- `OutgoingResponse` — Response to send (bot_id, chat_id, response_type, payload dict)
- `EventType` — Enum: message, command, callback_query
- `ChatType` — Enum: private, group, supergroup, channel

## Media Entities (future)

Full design: `doc/media_retrieval.md`

- `TelegramEvent` gains fields: `file_id`, `file_unique_id`, `media_status` ("pending" / "ready"), `media_url`
- `MessageEvent` gains fields: `is_reply`, `is_forward`
- `MediaConfigRule` — scope (global/chat/user), target (chat_id/user_id), content_types (list), action (eager/lazy)
- `MediaReadyEvent` — status update event type, references original event via `file_unique_id`

## Rules Engine (`rules.py`)

- `RoutingRule` — condition dict + target routing key
- `RoutingDecision` — matched bool + target + rule_idx
- `RulesEngine.evaluate(event, context, rules) -> RoutingDecision`
- `RulesEngine.resolve_subtype(event) -> str`
- `_match_condition` — matches 15 condition keys against event + context
  - `event_type`, `event_subtype`, `chat_type`, `command`, `command_starts_with`
  - `has_media`, `media_type`, `user_role`
  - `user_id`, `chat_id`, `text_contains`, `caption_contains`, `callback_data`
  - `is_reply`, `is_forward`
