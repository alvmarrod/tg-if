# Guía de Configuración y Enrutamiento — tg-if

## Visión General

**tg-if** es un gateway de Telegram MTProto que recibe eventos vía Pyrofork,
los evalúa contra un motor de reglas (`RulesEngine`), y publica los eventos
coincidentes en RabbitMQ (AMQP) para que suscriptores externos los consuman.
También consume respuestas de los suscriptores desde la cola `outgoing.responses`
y las envía a Telegram.

### Flujo de Alto Nivel

```text
Telegram ──(MTProto)──> tg-if ──(RabbitMQ AMQP)──> Suscriptores
                            ^                            │
                            │── outgoing.responses <─────│
                            │                            │
                             │── GET /files/ (media) ─────│
                             │── POST /upload/{bot_id) ─│
                             │    (envío de archivos)   │
                                (HTTP, no AMQP)
```

### Topología de AMQP

tg-if declara en su arranque:

| Exchange       | Tipo   | Propósito                                         |
|----------------|--------|---------------------------------------------------|
| `tg-if.events`  | topic  | tg-if publica eventos → suscriptores consumen      |
| `tg-if.responses` | direct | Suscriptores publican → tg-if consume |

Y tres colas duraderas en `tg-if.responses`:

| Cola                    | Routing Key              | Handler                         |
|-------------------------|--------------------------|---------------------------------|
| `outgoing.responses`     | `"response"`             | `ResponseConsumer` → Telegram   |
| `media-config`           | `"media-config"`         | Gestión de política de descarga |
| `subscriber-commands`    | `"subscriber-commands"`  | Registro de comandos del bot    |

---

## 1. Cómo Publica tg-if — El Motor de Reglas

### Archivo `config/bots.json`

Cada bot define reglas de enrutamiento. Ejemplo real:

```json
{
  "bots": [
    {
      "name": "chapter-notifier",
      "api_id": 23283537,
      "api_hash": "...",
      "session_file": "sessions/chapter_notifier.session",
      "bot_token": "...",
      "routing_rules": [
        {
          "condition": { "event_type": "command" },
          "target": "incoming.events.supportbot.commands"
        },
        {
          "condition": { "event_type": "message" },
          "target": "incoming.events.supportbot.messages"
        }
      ]
    }
  ]
}
```

### ¿Qué hace tg-if con esas reglas?

1. Un usuario de Telegram envía un mensaje al bot `chapter-notifier`.
2. Pyrofork recibe el evento, tg-if lo envuelve como `TelegramEvent`.
3. El `RulesEngine` evalúa el evento contra las condiciones de cada regla.
4. Si la condición coincide (ej. `event_type = "command"`), el `RulesEngine` devuelve el `target`.
5. `EventDispatcher._build_envelope()` arma un **envelope JSON** con todos los datos.
6. `Publisher.publish(routing_key=target, message=envelope)` publica en el exchange `tg-if.events`.

**La routing key se usa literalmente** — no hay transformación. Si el `target`
es `"incoming.events.supportbot.commands"`, esa es la routing key exacta.

### Envelope del Evento (lo que recibe el suscriptor)

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1706543210.123,
  "bot_id": "chapter-notifier",
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

---

## 2. Ejemplos Completos de Enrutamiento

### Ejemplo 1: Usuario escribe `/start` en Telegram

```text
Usuario                     tg-if                           RabbitMQ                     Suscriptor
  │                           │                                │                            │
  │── /start ─────────────────>│                                │                            │
  │   (MTProto)                │                                │                            │
  │                           │                                │                            │
  │                           │ RulesEngine evalúa:            │                            │
  │                           │ condición: event_type=command   │                            │
  │                           │ target: incoming.events.        │                            │
  │                           │         supportbot.commands     │                            │
  │                           │                                │                            │
  │                           │── publish ─────────────────────>│                            │
  │                           │   exchange: tg-if.events        │                            │
  │                           │   routing_key:                  │                            │
  │                           │   "incoming.events.             │                            │
  │                           │    supportbot.commands"         │                            │
  │                           │                                │                            │
  │                           │                                │ routing_key match ─────────>│
  │                           │                                │  patrón:                    │
  │                           │                                │  "incoming.events.          │
  │                           │                                │   supportbot.#"             │
  │                           │                                │                            │
  │                           │                                │                            │ [Procesa el comando]
```

**¿Quién hace qué?**

- **Usuario**: escribe `/start` en Telegram.
- **tg-if**: recibe el evento, lo evalúa con las reglas, publica en `tg-if.events`
  con routing key `"incoming.events.supportbot.commands"`.
- **RabbitMQ**: el exchange `tg-if.events` (topic) encamina el mensaje a las colas
  que tienen un binding cuyo patrón coincida.
- **Suscriptor**: tiene una cola propia vinculada al exchange `tg-if.events`
  con patrón `"incoming.events.supportbot.#"`. Recibe el mensaje.

---

### Ejemplo 2: Suscriptor responde al chat

```text
Suscriptor                  RabbitMQ                        tg-if                     Usuario
  │                            │                             │                          │
  │── publish ────────────────>│                             │                          │
  │   exchange:                │                             │                          │
  │   tg-if.responses          │                             │                          │
  │   routing_key:             │                             │                          │
  │   "response"               │                             │                          │
  │   body: {                  │                             │                          │
  │     "bot_id":              │                             │                          │
  │      "chapter-notifier",   │                             │                          │
  │     "chat_id": 12345,      │                             │                          │
  │     "response_type":       │                             │                          │
  │      "text",               │                             │                          │
  │     "payload": {           │                             │                          │
  │       "text": "¡Hola!"     │                             │                          │
  │     }                      │                             │                          │
  │   }                        │                             │                          │
  │                            │                             │                          │
  │                            │── consumer ────────────────>│                          │
  │                            │   (cola:                    │                          │
  │                            │   outgoing.responses)       │                          │
  │                            │                             │                          │
  │                            │                             │── send_message ──────────>│
  │                            │                             │   (MTProto)               │
  │                            │                             │                          │ ¡Hola!
```

**¿Quién hace qué?**

- **Suscriptor**: publica en `tg-if.responses` con routing key `"response"`.
- **tg-if**: tiene un `Consumer` escuchando en la cola `outgoing.responses`,
  vinculada con routing key `"response"`. Al recibir el mensaje, `ResponseConsumer`
  procesa el `OutgoingResponse` y llama al método `send_text` (o el que corresponda).
- **Usuario**: recibe el mensaje en Telegram.

---

### Ejemplo 3: Usuario hace clic en un botón inline

```text
Usuario                     tg-if                             RabbitMQ                   Suscriptor
  │                           │                                 │                           │
  │── clic botón ────────────>│                                 │                           │
  │   (callback_data:         │                                 │                           │
  │    "option_1")            │                                 │                           │
  │                           │                                 │                           │
  │                           │ RulesEngine evalúa:             │                           │
  │                           │ condición: event_type=          │                           │
  │                           │   callback_query                │                           │
  │                           │ target: incoming.events.        │                           │
  │                           │         supportbot.callbacks    │                           │
  │                           │                                 │                           │
  │                           │── publish ──────────────────────>│                           │
  │                           │   (envelope incluye:            │                           │
  │                           │   callback_id,                  │                           │
  │                           │   callback_data,                │                           │
  │                           │   message_id)                   │                           │
  │                           │                                 │                           │
  │                           │                                 │ routing_key match ────────>│
  │                           │                                 │                           │
  │                           │                                 │                           │ [Procesa callback]
  │                           │                                 │                           │
  │                           │                                 │  publica 2 respuestas:     │
  │                           │                                 │  1. answer_callback_query  │
  │                           │                                 │  2. edit_message_text      │
  │                           │                                 │                           │
  │                           │<── consumer (outgoing.responses)───┘                           │
  │                           │                                 │                           │
  │                           │── answer_callback_query ───────>│                           │
  │                           │   (muestra "Procesando...")     │                           │
  │                           │── edit_message_text ───────────>│                           │
  │                           │   (cambia texto del mensaje)    │                           │
```

**¿Quién hace qué?**

- **Usuario**: hace clic en un botón inline.
- **tg-if**: recibe `CallbackQueryEvent`, lo publica en `tg-if.events` con
  routing key `"incoming.events.supportbot.callbacks"`.
- **Suscriptor**: recibe el evento (incluye `callback_id`, `callback_data`, `message_id`).
  Publica dos respuestas en `tg-if.responses` con routing key `"response"`.
- **tg-if**: recibe ambas, envía `answer_callback_query` y `edit_message_text` a Telegram.
- **Usuario**: ve el toast "Procesando..." y el texto del mensaje actualizado.

---

### Ejemplo 4: Suscriptor registra comandos del bot

```text
Suscriptor                    RabbitMQ                         tg-if
  │                             │                               │
  │── publish ────────────────>│                               │
  │   exchange:                │                               │
  │   tg-if.responses          │                               │
  │   routing_key:             │                               │
  │   "subscriber-commands"    │                               │
  │   body: {                  │                               │
  │     "action": "register",  │                               │
  │     "bot_id":              │                               │
  │      "chapter-notifier",   │                               │
  │     "subscriber_id":       │                               │
  │      "svc_notifications",  │                               │
  │     "commands": [          │                               │
  │       {"command":          │                               │
  │        "start",            │                               │
  │        "description":      │                               │
  │        "Iniciar bot"}      │                               │
  │     ]                      │                               │
  │   }                        │                               │
  │                             │                               │
  │                             │── consumer ──────────────────>│
  │                             │   (cola:                     │
  │                             │   subscriber-commands)        │
  │                             │                               │
  │                             │                               │── BotCommandRegistry
  │                             │                               │   .register()
  │                             │                               │
  │                             │                               │── TelegramClient
  │                             │                               │   .set_bot_commands()
  │                             │                               │
  │                             │                               │ [Menú del bot actualizado]
```

**¿Quién hace qué?**

- **Suscriptor**: publica en `tg-if.responses` con routing key `"subscriber-commands"`.
- **tg-if**: `SubscriberCommandHandler` procesa, registra en `BotCommandRegistry`,
  y llama a `TelegramClient.set_bot_commands()` para reflejar los cambios
  en el menú del bot de Telegram.

---

## 3. Cómo Consume el Suscriptor — Paso a Paso

### 3.1. Crear una cola y vincularla

El suscriptor **debe crear su propia cola** y vincularla al exchange `tg-if.events`.
tg-if **nunca crea colas para suscriptores**.

```python
import asyncio
import json
import aio_pika

RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"

async def main():
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        ch = await conn.channel()
        await ch.set_qos(prefetch_count=10)

        # 1. Obtener el exchange donde tg-if publica
        exchange = await ch.get_exchange("tg-if.events")

        # 2. Crear cola propia (el nombre lo eliges tú)
        queue = await ch.declare_queue(
            "mi-servicio-eventos", durable=True
        )

        # 3. Vincular la cola con un patrón de routing key
        #    Recibe TODOS los eventos del bot "chapter-notifier"
        await queue.bind(exchange, routing_key="incoming.events.supportbot.#")

        #    También puedes usar patrones más específicos:
        #    "incoming.events.supportbot.commands"  → solo comandos
        #    "incoming.events.#"                     → todos los bots
        #    "incoming.events.*.text.#"              → solo mensajes de texto

        async with queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    body = json.loads(msg.body.decode())
                    print(f"Recibido: {body['event_type']}")
                    print(f"  chat_id: {body['chat_id']}")
                    print(f"  payload: {body['payload']}")

asyncio.run(main())
```

### 3.2. Enviar una respuesta a Telegram

Para responder a un evento, el suscriptor publica en `tg-if.responses`
con routing key `"response"`:

```python
async def send_text_reply(conn, bot_id, chat_id, text):
    ch = await conn.channel()
    exchange = await ch.get_exchange("tg-if.responses")

    body = {
        "response_id": "660e8400-e29b-41d4-a716-446655440001",
        "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        "timestamp": 1706543215.456,
        "bot_id": bot_id,
        "chat_id": chat_id,
        "response_type": "text",
        "payload": {"text": text},
        # "reply_to": "mi-cola-resultados"  # opcional, para recibir estado de entrega
    }

    msg = aio_pika.Message(
        body=json.dumps(body).encode(),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await exchange.publish(msg, routing_key="response")
```

### 3.3. Registrar comandos del bot

```python
async def register_commands(conn):
    ch = await conn.channel()
    exchange = await ch.get_exchange("tg-if.responses")

    body = {
        "action": "register",
        "bot_id": "chapter-notifier",
        "subscriber_id": "svc_notifications",
        "commands": [
            {"command": "start",    "description": "Iniciar el bot"},
            {"command": "help",     "description": "Mostrar ayuda"},
            {"command": "config",   "description": "Configurar preferencias"},
        ],
    }

    msg = aio_pika.Message(
        body=json.dumps(body).encode(),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await exchange.publish(msg, routing_key="subscriber-commands")
```

---

## 4. Patrones de Routing Key para Vincular Colas

Exchange `tg-if.events` es de tipo **topic**.
Los patrones usan la notación AMQP estándar:

| Patrón | Coincide con |
|--------|-------------|
| `incoming.events.supportbot.#` | Todos los eventos del bot `supportbot` |
| `incoming.events.*.commands.#` | Comandos de cualquier bot |
| `incoming.events.*.text.#` | Mensajes de texto de cualquier bot |
| `incoming.events.#` | Todos los eventos de todos los bots |
| `incoming.events.supportbot.commands` | Solo la routing key exacta (sin subtipos) |

### Convención esperada de routing keys

```text
incoming.events.{bot_name}.{event_type}.{subtype}
```

- `bot_name`: nombre del bot (ej. `supportbot`, `chapter-notifier`).
- `event_type`: `command`, `message`, `callback_query`, `edited_message`.
- `subtype`: `text` para comandos/callbacks; tipo de media (`photo`, `video`, `document`, `audio`) para mensajes.

---

## 5. Resumen del Flujo Completo

### De Telegram al Suscriptor

```text
Usuario escribe /start
  └─> Pyrofork (MTProto) recibe el mensaje
       └─> tg-if crea TelegramEvent + RoutingContext
            └─> RulesEngine evalúa contra las reglas del bot
                 └─> Coincide: event_type == "command"
                 └─> target: "incoming.events.supportbot.commands"
                      └─> EventDispatcher arma envelope JSON
                           └─> Publisher.publish("incoming.events.supportbot.commands", envelope)
                                └─> Exchange tg-if.events (topic)
                                     └─> Routing key "incoming.events.supportbot.commands"
                                          └─> Coincide con binding del suscriptor (patrón "supportbot.#")
                                               └─> Suscriptor recibe el mensaje en su cola
```

### Del Suscriptor a Telegram

```text
Suscriptor publica en tg-if.responses
  routing_key: "response"
  body: { bot_id, chat_id, response_type: "text", payload: { text: "¡Hola!" } }
  └─> Exchange tg-if.responses (direct)
       └─> Routing key "response"
            └─> Cola outgoing.responses
                 └─> Consumer de tg-if recibe
                      └─> ResponseConsumer.handle()
                           └─> TelegramClient.send_text(chat_id, "¡Hola!")
                                └─> Pyrofork envía a Telegram
                                     └─> Usuario ve "¡Hola!"
```

---

## Notas Importantes

1. **tg-if nunca crea colas para suscriptores en `tg-if.events`**.
   El suscriptor es responsable de crear su cola y vincularla.

2. **El `Consumer` de tg-if (clase interna) solo se vincula a `tg-if.responses`**.
   No consume eventos de `tg-if.events`.

3. **La routing key del `target` es un string libre**. No hay validación
   de que siga la convención documentada, pero se recomienda seguir el formato
   `incoming.events.{bot_name}.{event_type}.{subtype}`.

4. **Para recibir eventos, el suscriptor necesita su propio cliente AMQP**
   (aio-pika, pika, amqplib, etc.) — no usa ninguna librería de tg-if.

5. **Para enviar respuestas**, el cuerpo del mensaje debe coincidir con
   el esquema `OutgoingResponse`. Ver `doc/subscriber_interface.md` para

6. **Para archivos > 16 MB**, tg-if expone un endpoint HTTP de upload.
   Ver [`doc/subscriber_media_interface_esp.md`](subscriber_media_interface_esp.md) para
   el protocolo completo de subida de archivos.
   los detalles completos de cada `response_type`.
