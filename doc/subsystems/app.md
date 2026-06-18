# Application Layer

**Location:** `src/app/`

## EventDispatcher

- Input: TelegramEvent, RoutingContext
- Evaluates rules per bot via RulesEngine
- Builds envelope, publishes to matched routing key
- Increments ServiceMetrics counters

## ResponseConsumer

- Input: dict body from RabbitMQ Consumer
- Validates as OutgoingResponse
- Routes to correct TelegramClient via bot_id
- Calls send_{type} method (or edit_/answer_ method directly)
- Increments ServiceMetrics counters

## ReceiverService

- Orchestrator: wires all components
- Creates TelegramClient per bot config
- Creates AdminNotifier + AdminCommandHandler if admin config present
- Runs health monitor loop (60s)
- Starts/stops everything via start()/stop()
- Wire Prometheus metrics_exporter increments

## AdminNotifier

- AdminSignalType enum: RESPONSE_FAILED, COMPONENT_CONNECTED, COMPONENT_DISCONNECTED
- notify(signal_type, **kwargs) sends formatted DM to admin user
- Wraps dedicated admin TelegramClient

## AdminCommandHandler

- handle(event, context) — parses DM commands, dispatches to handlers
- Commands: see `doc/monitor_cmds.md` for full reference
- Runtime rule mutation via `/rule-add` and `/rule-remove` with snapshot persistence
- Sends responses as new DMs via admin client

## ServiceMetrics

- Per-bot counters: received, matched, published
- Per-target counters: events per routing target with rolling hour window
- Response counters: consumed, sent, failed
- snapshot() returns dict

## LogBuffer

- Ring buffer (max 200 entries) as structlog processor

## Media Components (future)

Full design: `doc/media_retrieval.md`

### MediaConfigManager

- Holds eager/lazy rules in memory (global, chat, user, content_type scopes)
- Applies precedence: user > chat > content_type > global
- Evaluates an event against rules → returns `eager` or `lazy`
- Updated via AdminCommandHandler or AMQP config consumer

### MediaDownloader

- Background async task triggered on eager-matched events
- Downloads media via Pyrofork `download_media(file_id, in_memory=True)`
- Writes to disk cache keyed by `file_unique_id`
- Runs concurrently with event publication (non-blocking)

### BotCommandRegistry

- In-memory dict `{bot_id: {subscriber_id: BotCommandRegistration}}`
- `register(bot_id, subscriber_id, commands)` — merges, detects conflicts
- `deregister(bot_id, subscriber_id)` — removes subscriber's commands
- `get_commands(bot_id)` — returns merged flat list for `set_bot_commands`

### SubscriberCommandHandler

- AMQP message handler for `subscriber-commands` queue
- Validates `SubscriberCommandEnvelope`, dispatches to `BotCommandRegistry`
- On successful register/deregister, calls `TelegramClient.set_bot_commands()`
- Publishes `SubscriberCommandResponse` to `reply_to` queue if provided
