# Infrastructure Layer

**Location:** `src/infrastructure/`

## Config (`config.py`)
- AppConfig: broker + bots + admin + health_port
- BotConfig: name, api_id, api_hash, session_file, routing_rules
- AdminBotConfig: extends BotConfig with user_id
- ConfigLoader: env vars for broker, JSON file for bots

## Telegram Client (`telegram/client.py`)
- TelegramClient.start() / stop() / health()
- 6 send methods: send_text, send_photo, send_video, send_document, send_audio, send_action
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

## Metrics Exporter (`metrics_exporter.py`)
- Prometheus Counter and Gauge objects
- generate_metrics() -> str
