# RabbitMQ Setup for tg-if

## Version

`rabbitmq:4-alpine` — standard AMQP 0-9-1 protocol.

## Connection

| Parameter | Default | Override |
|-----------|---------|----------|
| Host | `localhost` | `RABBITMQ_HOST` |
| Port | `5672` | `RABBITMQ_PORT` |
| User | `guest` | `RABBITMQ_USER` |
| Password | `guest` | `RABBITMQ_PASSWORD` |
| VHost | `/` | `RABBITMQ_VHOST` |

Connection URL format: `amqp://{user}:{password}@{host}:{port}/{vhost}`

## Topology (Declared on Connect)

tg-if declares these on startup. The broker must allow application-level exchange/queue declaration.

### Exchanges

| Name | Type | Durable |
|------|------|---------|
| `tg-if.events` | topic | yes |
| `tg-if.responses` | direct | yes |

### Queues (Declared by tg-if)

| Queue | Durable | Bound To | Routing Key |
|-------|---------|----------|-------------|
| `outgoing.responses` | yes | `tg-if.responses` | `response` |
| `media-config` | yes | `tg-if.responses` | `media-config` |
| `subscriber-commands` | yes | `tg-if.responses` | `subscriber-commands` |

### Queues (Declared by Subscribers)

Subscribers create their own queues and bind them to `tg-if.events` with routing key patterns. Examples:

| Queue | Binding Pattern | Subscriber |
|-------|----------------|------------|
| `my-subscriber.alerts` | `incoming.events.aibot.#` | Catches all events for `aibot` |
| `my-subscriber.text` | `incoming.events.*.text.#` | Catches text messages from all bots |

Message schemas for all three `tg-if.responses` queues: see [`subscriber_interface.md`](subscriber_interface.md).

## Event Flow

```text
Telegram → Pyrofork → tg-if → tg-if.events (topic) → Subscriber queue
                                              ↑
Subscriber → tg-if.responses (direct) → outgoing.responses → tg-if
```

1. Incoming Telegram events are published to `tg-if.events` with routing key `incoming.events.{bot_name}.{type}.{subtype}`
2. Subscribers consume from their own queues bound to `tg-if.events`
3. Subscribers publish responses to `tg-if.responses` with routing key `response`
4. tg-if consumes from `outgoing.responses` and sends replies via Telegram

## Minimal Docker Test

```text
docker run -d --name tg-if-rabbitmq -p 5672:5672 rabbitmq:4-alpine
```

Connection succeeds with defaults (guest/guest, localhost:5672, vhost /). The integration tests under `tests/integration/` use testcontainers to spin this up automatically.

## Required Broker Capabilities

- Standard AMQP 0-9-1 (not Streams)
- Virtual host support
- Application-level exchange and queue declaration
- Topic exchange routing
- Direct exchange routing
