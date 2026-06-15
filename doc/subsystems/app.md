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
- Calls send_{response_type} method
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

- handle(event, context) — parses DM commands, dispatches to 5 handlers
- Commands: /help, /status, /bots, /rules --bot <name>, /log [n]
- Sends responses as new DMs via admin client

## ServiceMetrics

- Per-bot counters: received, matched, published
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
