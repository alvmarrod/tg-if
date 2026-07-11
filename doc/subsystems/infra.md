# Infrastructure Layer

**Location:** `src/infrastructure/`

## Config (`config.py`)

- AppConfig: broker + bots + admin + health_port
- BotConfig: name, api_id, api_hash, session_file, routing_rules
- AdminBotConfig: extends BotConfig with user_id
- ConfigLoader: env vars for broker, JSON file for bots

## Telegram Client (`telegram/client.py`)

- TelegramClient.start() / stop() / health()
- 8 send/edit methods: send_text, send_photo, send_video, send_document, send_audio, send_media_group, edit_message_text, answer_callback_query
- event_callback: optional callable for incoming events
- Handlers always registered, guarded internally
- set_event_callback() for post-construction wiring

## Telegram Handlers (`telegram/handlers.py`)

- Convert MTProto events to domain entities
- Extract routing context (chat_type, command, media, etc.)
- Build reply markup from payload

## RabbitMQ Manager (`broker/rabbitmq.py`)

- RabbitMQManager.connect() / disconnect() / health()
- Declares tg-if.events (topic, durable) and tg-if.responses (direct, durable)

## Publisher (`broker/publisher.py`)

- Publisher.publish(routing_key, message) to tg-if.events

## Consumer (`broker/consumer.py`)

- Consumer with internal retry (max_retries=3, linear backoff 1s/2s/3s)
- on_failed callback for permanent failures
- start() / stop()

## Health (`health.py`)

- aiohttp server on configurable port
- GET /health — JSON status
- GET /metrics — Prometheus text format

## Media Retrieval (`media/` — future)

Full design: `doc/media_retrieval.md`

### HTTP File Endpoint (on health server)

- `GET /files/{bot_id}/{file_id}` — streams media on demand via PyroTGFork
- Checks disk cache first (by `file_unique_id`), falls back to lazy download from Telegram
- Write-through: lazy downloads populate the cache for subsequent requests
- Integrated into existing health aiohttp server

### Disk Cache Store

- Files stored at `/data/media/{bot_id}/{file_unique_id}.{ext}`
- Tracks access count, last access time, stored timestamp
- Dedup: same `file_unique_id` → single file regardless of forwards or repeats

### Media Config Consumer (future)

- Consumes from `tg-if.media-config` AMQP queue
- Subscribers publish media download policy rules (eager/lazy per scope)
- In-memory rule store (persistence TBD)

### Eager Download Background Task (future)

- On event receipt, checks config for eager match
- If match: async download to disk cache in background
- Does not block event publication

## Metrics Exporter (`metrics_exporter.py`)

- Prometheus Counter and Gauge objects
- generate_metrics() -> str
