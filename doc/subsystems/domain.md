# Domain Layer

**Location:** `src/domain/`

## Entities

- `TelegramEvent` — Incoming event from Telegram (event_type, chat_id, user_id, raw_payload, bot_id)
- `RoutingContext` — Extracted metadata for rule matching (chat_type, command, has_media, media_type, user_role, text)
- `OutgoingResponse` — Response to send (bot_id, chat_id, response_type, payload dict)
- `EventType` — Enum: message, command, callback_query
- `ChatType` — Enum: private, group, supergroup, channel

## Rules Engine (`rules.py`)

- `RoutingRule` — condition dict + target routing key
- `RoutingDecision` — matched bool + target + rule_idx
- `RulesEngine.evaluate(event, context, rules) -> RoutingDecision`
- `RulesEngine.resolve_subtype(event) -> str`
- `_match_condition` — matches 10 condition keys against event + context
