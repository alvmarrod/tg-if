# Chat Export System

On-demand export of full chat history (messages, media, reactions) for any chat where the configured user account is a member, using a pre-authenticated user MTProto session (not a bot). All export work goes directly to disk — no AMQP involved.

## Admin Commands

### `/chats`

Lists all dialogs the user account has access to as a table.

| Column | Description |
|--------|-------------|
| Name | Chat title |
| ID | Telegram chat ID (signed 64-bit) |
| Type | group / supergroup / channel |
| Members | Member count |
| Read | Bot can read messages in this chat |
| Write | Bot can send messages in this chat |
| Exportable | All prerequisites met for export |

The admin uses this to discover the target `chat_id` for `/export`.

> **Deferred:** `--search` filter for large chat lists. Logged in code as `# TODO: deferred`.

### `/export <chat_id> [--since <date|msg_id>] [--parallelism <N>]`

Triggers a full history export for the given chat.

| Argument | Required | Description |
|----------|----------|-------------|
| `chat_id` | Yes | Telegram chat ID from `/chats` |
| `--since` | No | Start point — accepts a date (`2026-01-01`) or a message ID. Omit = full history. |
| `--parallelism` | No | Concurrent media download workers (default: 1). |

**Behavior:**

- Without `--since`: re-export the entire chat history (overwrites existing export).
- With `--since` (date): uses Pyrofork's `offset_date` as an approximation, then discards messages before the cutoff.
- With `--since` (message ID): starts from that message ID.
- Only one export can run at a time. If an export is already in progress, `/export` is rejected with an "already running" error.

**Control buttons:**
The progress message includes an inline keyboard:

- ⏸️ **Pause** — suspends iteration. Download in-flight may finish but no new pages are fetched.
- ▶️ **Resume** — continues a paused export.
- ⏹️ **Cancel** — aborts the export. Any export already written to disk remains.

Pause/resume state is in-memory only — not persisted across process restarts.

**Progress:**
The bot sends a single progress message and edits it in-place as the export progresses:

```text
⬛⬛⬛⬛⬛⬛⬛⬛⬜⬜ 8250/9847 msgs  83.8%
```

The bar uses 20 blocks total, calculated as `filled = floor(20 * processed / total)`. Filled blocks use `⬛`, remaining use `⬜`.

After completion, the progress message is edited to a completion summary and the inline keyboard is removed:

```text
✅ Export complete — chat -100123456789
   9847 messages · 2024-03-12 – 2026-07-01
   142 media files · 2.3 GB
   /data/exports/-100123456789/_summary.json
```

## Output Structure

```text
/data/exports/
└── {chat_id}/
    ├── _summary.json
    ├── 2024-03.json
    ├── 2024-04.json
    ├── ...
    ├── 2026-07.json
    └── media/
        ├── animation/
        │   └── {file_unique_id}.mp4
        ├── audio/
        │   └── {file_unique_id}.mp3
        ├── document/
        │   └── {file_unique_id}_{filename}
        ├── photo/
        │   └── {file_unique_id}.jpg
        ├── sticker/
        │   └── {file_unique_id}.webp
        └── video/
            └── {file_unique_id}.mp4
```

Media files are deduplicated by `file_unique_id` within a single export — if the same file appears in multiple messages it is downloaded once.

Media must be written to a **bind-mounted host path** so the exported data persists and is accessible from outside the container.

### JSON Message Format

One JSON object per message, one per line within the monthly file (JSONL):

```json
{
  "message_id": 123,
  "date": "2024-03-12T14:30:00+00:00",
  "edit_date": "2024-03-12T14:35:00+00:00",
  "from_user": {
    "id": 67890,
    "is_bot": false,
    "first_name": "Alice",
    "last_name": null,
    "username": "alice_42",
    "language_code": "en"
  },
  "text": "Hello world",
  "caption": null,
  "media": {
    "type": "photo",
    "file_unique_id": "AQAD...",
    "file_id": "AgAC...",
    "file_size": 123456,
    "width": 1920,
    "height": 1080,
    "local_path": "media/photo/AQAD....jpg"
  },
  "reactions": [
    {"emoji": "👍", "count": 3},
    {"emoji": "❤️", "count": 1}
  ],
  "reply_to_message_id": 100,
  "is_forward": false,
  "forward_from": null,
  "forward_date": null
}
```

Fields:

- `media`: present only if the message contains media. The `type` field maps to the media subdirectory (e.g. `"photo"` → `media/photo/`). The `local_path` is relative to the export root (`/data/exports/{chat_id}/`).
- `reactions`: present only if the message has reactions. Each entry is `{emoji, count}`. Only the aggregate count is included (matching `MessageReactionCountUpdatedEvent`), not per-user reaction details.
- `edit_date`: present only if the message was edited (null otherwise).

### `_summary.json`

```json
{
  "chat_id": -100123456789,
  "chat_name": "My Group",
  "exported_at": "2026-07-01T12:00:00+00:00",
  "message_count": 9847,
  "first_message_id": 1,
  "first_message_date": "2024-03-12T14:30:00+00:00",
  "last_message_id": 9847,
  "last_message_date": "2026-07-01T11:59:00+00:00",
  "media_count": 142,
  "media_total_bytes": 2469600000,
  "since_message_id": null,
  "since_date": null,
  "files": [
    "2024-03.json",
    "2024-04.json",
    "2024-05.json",
    "2024-06.json",
    "2024-07.json",
    "2024-08.json",
    "2024-09.json",
    "2024-10.json",
    "2024-11.json",
    "2024-12.json",
    "2025-01.json",
    "2025-02.json",
    "2025-03.json",
    "2025-04.json",
    "2025-05.json",
    "2025-06.json",
    "2025-07.json",
    "2025-08.json",
    "2025-09.json",
    "2025-10.json",
    "2025-11.json",
    "2025-12.json",
    "2026-01.json",
    "2026-02.json",
    "2026-03.json",
    "2026-04.json",
    "2026-05.json",
    "2026-06.json",
    "2026-07.json"
  ]
}
```

The `files` array lists every monthly JSONL file produced by the export. A consumer can scan this list to read the data incrementally.

`first_message_id` / `last_message_id` correspond to the oldest and newest message IDs in the export. These can be passed back to `--since` for subsequent incremental exports.

## Implementation Plan

### Phase 1: Admin Commands

- Define `ChatInfo` dataclass/Pydantic model for `/chats` output
- Add `/chats` command to `AdminCommandHandler` — iterate over `client.get_dialogs()`, gather permissions
- Add `/export` command that parses `chat_id`, `--since`, `--parallelism` and spawns an async export task
- Add `/export-cancel` command — alias for cancelling via text (inline keyboard is the primary path)
- Progress message management: send once, edit in-place via `edit_message_text`, attach inline keyboard for pause/resume/cancel

### Phase 2: Export Engine

- `ChatExportEngine` class with:
  - `export_chat(chat_id, since, parallelism)` — the main export coroutine
  - `pause()`, `resume()`, `cancel()` — control methods
  - Single-task lock (`asyncio.Lock`) — reject `/export` if running
  - In-memory state: `asyncio.Event` for pause/resume, `asyncio.Event` for cancel
- Uses `client.get_chat_history(chat_id)` with pagination
- Collects total message count first (for progress bar), then iterates
- For each message:
  - Serialize to JSONL format
  - If media present: check if `file_unique_id` was already downloaded; if not, enqueue for concurrent download via `asyncio.Semaphore(parallelism)`
  - Append to monthly JSONL file
- Periodically check pause event (blocks) and cancel event (exits cleanly)
- Generate `_summary.json` at end

### Phase 3: Media Download

- Dedup via `set[str]` of seen `file_unique_id`s per export session
- Download into `media/{type}/` subdirectory using `client.download_media()`
- Extension resolved from Telegram's MIME type or file name
- Downloads run concurrently up to `parallelism` limit via `asyncio.Semaphore`
- Errors logged but do not abort export — failed media entries note `"download_error": true`

## Requirements

- A **user MTProto session** must be pre-authenticated before deploying.
  Run `python tools/auth_user.py` once to create the session file interactively.
  The session is stored on disk and reused on subsequent starts.
- The export directory must be on a **bind mount** to persist to the host filesystem
- The user account must have access to the target chat (member)

## Out of Scope (v1)

- Export to AMQP or streaming
- Per-user reaction detail (only aggregate counts)
- Multiple media versions (edits overwrite the latest)
- Automatic periodic exports
- Compression of export files
- Resume interrupted exports across process restarts
- `--max-messages` limit flag
- `/chats --search` filter
