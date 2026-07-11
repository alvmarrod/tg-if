# Subscriber Media Interface — Upload de Archivos a Telegram

## 1. Visión General

Cuando un suscriptor necesita enviar un archivo (imagen, video, audio,
documento, comprimido, etc.) a un chat de Telegram a través de tg-if,
hay dos caminos:

| Método | Límite | Cuándo usarlo |
|--------|--------|---------------|
| **Inline en AMQP** | ≤ 16 MB | Archivos pequeños: el binario va en el payload del mensaje AMQP |
| **Upload por HTTP** | Sin límite práctico | Archivos > 16 MB o cuando el suscriptor prefiera no codificar en AMQP |

Este documento describe el **método HTTP**, aplicable a cualquier tipo de archivo.

### Límite de AMQP

RabbitMQ tiene un límite práctico de ~16 MB por mensaje
(configurable vía `rabbitmq.conf`, pero 16 MB es el default seguro).
tg-if **no** acepta payloads inline que superen este tamaño.
Por encima de 16 MB, el suscriptor **debe** usar el endpoint de upload.

---

## 2. Flujo Secuencial (Upload First, Then AMQP)

El suscriptor **siempre sube el archivo primero** vía HTTP, y luego envía
el `OutgoingResponse` por AMQP referenciando el archivo por su hash.

```text
Consumer                               tg-if
   │                                      │
   │  ── 1. POST /upload/{bot_id} ──────>│   (HTTP multipart)
   │     (campo "file" con el binario)    │
   │                                      │
   │                                      │── SHA256 del contenido → hash
   │                                      │── ¿hash ya registrado?
   │                                      │    Sí → upload_id listo
   │                                      │    No → guarda en cache
   │                                      │         + registro en SQLite
   │                                      │
   │  <── { "upload_id": "upl_abc123",   ──│
   │         "cached": true/false,         │
   │         "file_id": "AgAC..."|null }   │
   │                                      │
   │  ── 2. OutgoingResponse ───────────>│   (AMQP, tg-if.responses)
   │     { response_type: "video",        │
   │       chat_id: 12345,                │
   │       payload: {                     │
   │         video: "upl_abc123",         │
   │         caption: "Video procesado"   │
   │       } }                            │
   │                                      │
   │                                      │── ResponseConsumer resuelve
   │                                      │   "upl_" → hash → file_id?
   │                                      │    Sí → send_video(file_id)  (sin re-upload)
   │                                      │    No → send_video(path_bytes) (upload+send)
   │                                      │         → extrae file_id del Message
   │                                      │         → actualiza registro
   │                                      │
   │                                      │── PyroTGFork envía a Telegram
   │                                      │         └─> Usuario recibe el archivo
```

**Importante:** solo hay **una** transacción por envío.
El `POST /upload` y el `OutgoingResponse` son dos pasos secuenciales
de la misma operación, no dos intentos separados.

Si el archivo ya fue subido antes (mismo hash), el paso 1 es instantáneo
y devuelve `cached: true` + el `file_id` de Telegram si existe.
El paso 2 entonces usará el `file_id` directamente sin re-upload.

---

## 3. Endpoint HTTP — POST /upload/{bot_id}

### 3.1. Petición

```http
POST /upload/{bot_id}
Content-Type: multipart/form-data
```

| Campo | Tipo | Obligatorio | Descripción |
|-------|------|-------------|-------------|
| `file` | archivo | sí | El binario del archivo a subir |
| `filename` | string (en multipart) | no | Nombre sugerido (para detectar extensión) |

El `bot_id` en la URL debe coincidir con el `bot_id` del `OutgoingResponse`
que referenciará este upload.

No hay límite de tamaño en el endpoint — tg-if recibe el archivo en streaming
y lo almacena en la caché interna (MinIO / filesystem).

### 3.2. Respuesta

```json
{
  "upload_id": "upl_abc123def456",
  "size": 12345678,
  "ext": "mp4",
  "cached": true,
  "file_id": "AgACAgQAAxkBAA...",
  "file_unique_id": "QQAD..."
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `upload_id` | string | Identificador para usar en el OutgoingResponse. Prefijo `upl_` + SHA256 del contenido. |
| `size` | integer | Tamaño en bytes |
| `ext` | string | Extensión detectada (por Content-Type o filename) |
| `cached` | boolean | `true` si ya existía en caché, `false` si es la primera vez |
| `file_id` | string o null | `file_id` de Telegram si ya fue enviado antes; `null` si es la primera vez |
| `file_unique_id` | string o null | `file_unique_id` de Telegram asociado |

### 3.3. Idempotencia

El endpoint es **idempotente**: mismo contenido binario → mismo SHA256 →
mismo `upload_id`. Si el hash ya está registrado, la respuesta es inmediata
sin transferencia de bytes ni re-upload a Telegram.

El suscriptor puede cachear localmente la relación
`(contenido → upload_id)` para saltarse el `POST /upload` en usos futuros
del mismo archivo.

### 3.4. Ejemplo con Python

```python
import hashlib
import requests

TGIF_UPLOAD = "http://tg-if:8080/upload"
TGIF_AMQP   = None  # tu conexión a RabbitMQ

def send_file_to_telegram(bot_id: str, chat_id: int, file_path: str,
                          caption: str = "") -> dict:
    # Paso 1: upload HTTP
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{TGIF_UPLOAD}/{bot_id}",
            files={"file": f},
        )
    data = resp.json()
    upload_id = data["upload_id"]

    # Paso 2: enviar OutgoingResponse por AMQP
    message = {
        "response_id": "uuid-del-momento",
        "correlation_id": "uuid-del-evento-original",
        "timestamp": 1706543215.456,
        "bot_id": bot_id,
        "chat_id": chat_id,
        "response_type": "document",  # video, photo, audio, etc.
        "payload": {
            "document": upload_id,
            "caption": caption,
        },
    }
    # publicar en exchange tg-if.responses, routing_key "response"
    # (código específico de tu librería AMQP)

    return data  # contiene upload_id, cached, file_id
```

---

## 4. Tipos de Media Soportados

Todos los `response_type` que aceptan un archivo en su `payload` pueden
usar `upl_<hash>` como valor.

| `response_type` | Clave en payload | ¿Soporta `upl_`? |
|----------------|------------------|------------------|
| `text` | — | No aplica |
| `photo` | `payload["photo"]` | ✅ Sí |
| `video` | `payload["video"]` | ✅ Sí |
| `document` | `payload["document"]` | ✅ Sí |
| `audio` | `payload["audio"]` | ✅ Sí |
| `media_group` | `payload["media"][n]["media"]` | ✅ Sí (cada item) |
| `edit_message_text` | — | No aplica |
| `answer_callback_query` | — | No aplica |

Para `media_group`, cada elemento del array `media` puede tener su propio
valor `upl_`:

```json
{
  "response_type": "media_group",
  "chat_id": 12345,
  "bot_id": "supportbot",
  "payload": {
    "media": [
      { "type": "photo", "media": "upl_foto_hash_1", "caption": "Foto 1" },
      { "type": "video", "media": "upl_video_hash_2", "caption": "Video 1" }
    ]
  }
}
```

### Umbral de uso recomendado

| Tamaño del archivo | Método recomendado |
|-------------------|-------------------|
| ≤ 16 MB | Inline en AMQP (binario en payload) o upload HTTP |
| > 16 MB | **Obligatorio** upload HTTP + `upl_` |

El límite de 16 MB es el máximo de AMQP. Aunque un archivo quepa en AMQP,
el suscriptor puede optar por upload HTTP si prefiere no codificar binarios
en el mensaje (ej. fotos grandes de ~10 MB, comprimidos, etc.).

---

## 5. Caché y Reuso de file_id

### 5.1. Registro persistente (SQLite)

tg-if mantiene un registro SQLite en `/data/uploads.db` con la tabla:

```sql
CREATE TABLE uploads (
    content_hash TEXT PRIMARY KEY,    -- SHA256 del contenido
    url_hash TEXT UNIQUE,             -- SHA256 de la URL (futuro, nullable)
    url TEXT,                         -- URL original (futuro, nullable)
    file_id TEXT,                     -- file_id de Telegram para reuso directo
    file_unique_id TEXT,              -- file_unique_id de Telegram
    bot_id TEXT NOT NULL,
    ext TEXT NOT NULL DEFAULT 'bin',
    size INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0
);
```

### 5.2. Comportamiento en ResponseConsumer

Cuando el `OutgoingResponse` contiene `upl_<hash>`:

1. **Buscar en registro** por `hash`:
   - ¿`file_id` existe? → usar `send_*(chat_id, video=file_id)`
     - Si Telegram rechaza el `file_id` (error `MEDIA_EMPTY`), caer al paso 2
     - Si éxito, actualizar `last_used_at` y `use_count`
   - ¿`file_id` no existe? → ir al paso 2

2. **Buscar en caché de bytes** (MinIO) por `{bot_id}/{hash}.{ext}`:
   - ¿Existe? → `send_*(chat_id, video=ruta_local)`
     - PyroTGFork sube y envía en una sola operación
     - Del `Message` retornado extraer `file_id` y `file_unique_id`
     - Actualizar registro: guardar `file_id` y `file_unique_id`
   - ¿No existe? → error definitivo: el upload_id no se reconoce

### 5.3. Beneficio

| Escenario | Acción | Resultado |
|-----------|--------|-----------|
| Primera vez que se sube un archivo | Upload a Telegram via PyroTGFork | Se obtiene file_id, se guarda |
| Mismo archivo, otro chat, otro momento | Se usa file_id directamente | Sin re-upload, respuesta inmediata |
| file_id expiró o es inválido | Fallback a bytes en MinIO, re-upload | Se obtiene nuevo file_id |
| MinIO purgado pero file_id válido | Se usa file_id directamente | Funciona sin bytes |

---

## 6. Manejo de Errores

### 6.1. Error: upload_id no encontrado

Si el `ResponseConsumer` resuelve `upl_<hash>` y no existe ni en registro
ni en caché de bytes, el mensaje falla definitivamente.
El suscriptor recibe un resultado de entrega con `status: "failed"`
si incluyó `reply_to` en el `OutgoingResponse`.

**Causa típica:** el suscriptor envió el `OutgoingResponse` antes de que
el `POST /upload` completara (violación del flujo secuencial), o el hash
está mal formado.

### 6.2. Error: file_id expirado

Si `send_*(video=file_id)` lanza `MediaEmpty` u otro error terminal
de archivo, tg-if:

1. Marca el `file_id` como obsoleto en el registro (lo pone a `null`)
2. Reintenta con los bytes en MinIO (sube y envía de nuevo)
3. Actualiza el registro con el nuevo `file_id`

El suscriptor no necesita hacer nada — la recuperación es automática.

### 6.3. Error: archivo demasiado grande para inline

Si el suscriptor intenta incluir un binario ≥ 16 MB en el payload AMQP,
tg-if rechaza el mensaje con un error de validación.
El suscriptor debe usar el endpoint HTTP.

---

## 7. Administración de la Caché de Uploads

Comandos separados de la caché de descargas (`/media-*`):

| Comando | Función |
|---------|---------|
| `/upload-list [--bot B]` | Lista archivos subidos (hash, ext, size, file_id, use_count, last_used) |
| `/upload-prune --older-than Nd [--bot B] [--keep-first N] [--max-size M]` | Elimina entradas no usadas (mismos parámetros que `/media-prune`) |
| `/upload-purge [--confirm] [--bot B]` | Elimina todos los uploads (solo metadata + bytes, no afecta file_id de Telegram) |

Ejemplo de `/upload-list`:

```text
hash         | ext  | size    | file_id         | uses | last_used
abc123def456 | mp4  | 45 MB   | AgAC...         | 3    | 2026-06-20T10:00
def789abc012 | zip  | 120 MB  | (null)          | 0    | 2026-06-19T08:00
```

---

## 8. Upload por URL (Futuro — v2)

En una versión posterior, el endpoint aceptará también una URL como origen:

```http
POST /upload/{bot_id}
Content-Type: application/json
{ "url": "https://cdn.ejemplo.com/video.mp4" }
```

tg-if descargará el contenido desde la URL, lo almacenará en caché,
y devolverá el mismo `upload_id`. La respuesta puede ser asíncrona
(202 Accepted) para archivos grandes.

El dedup funciona en dos niveles:

- **url_hash**: SHA256 de la URL → si ya se descargó antes, respuesta inmediata
- **content_hash**: SHA256 del contenido → si el mismo video llega por
  otra URL o por upload directo, se reusa todo

---

## 9. Resumen

```text
Archivo > 16 MB o el consumer prefiere no usar inline AMQP
  └─> POST /upload/{bot_id}  (HTTP multipart)
       └─> SHA256 → hash → ¿ya existe?
            ├─ Sí: upload_id + file_id listos (respuesta inmediata)
            └─ No: guardar bytes + registrar → upload_id
  └─> OutgoingResponse { payload.{key}: "upl_<hash>" }  (AMQP)
       └─> ResponseConsumer resuelve:
            ├─ file_id existe? → send(chat_id, file_id)  ← sin re-upload a Telegram
            └─ sin file_id?    → send(chat_id, ruta_bytes)
                                 └─ PyroTGFork upload+send
                                 └─ extrae file_id → guarda para próxima vez
```
