# Media Retrieval

**Date:** 2026-06-15  
**Status:** Approved  
**Roadmap:** `.agent/media-retrieval-roadmap.md`

## Problem

When Tg-if receives a message containing media (photo, video, audio, document, animation/gif), the event published to AMQP currently carries **metadata only** — `has_media`, `media_type`, `caption` — and the `raw_payload` dict is left empty. The subscriber gets no file ID, no URL, and no bytes.

If the subscriber needs the actual media content (e.g., for AI processing, moderation, archiving), it must obtain it somehow. The constraint is: **the subscriber must not communicate with Telegram directly** — that would bypass the gateway abstraction and force every subscriber to hold Telegram API credentials.

## Current State

```text
Telegram → message (video/photo) → Pyrofork → message_to_event()
                                                      │
                                                      ├─ has_media=True
                                                      ├─ media_type="video"
                                                      ├─ caption="..."
                                                      └─ raw_payload={}  ← file IDs discarded
```

The handler at `src/infrastructure/telegram/handlers.py:27` extracts minimal metadata and discards the `Message` object's file-specific attributes (`message.video.file_id`, etc.).

## Deduplication via file_unique_id

All 8 media types (photo, video, audio, document, animation/gif, voice, video note, sticker) carry two identifiers:

| Field | Stability | Can download? | Purpose |
|---|---|---|---|
| `file_id` | Per-session, expires | Yes | Short-lived access token |
| `file_unique_id` | Permanent, content-based | No | Identity — same across accounts, sessions, forwards |

`file_unique_id` is derived from Telegram's internal `media_id` (a 64-bit integer hash of the raw content). It remains identical when:

- A user sends the same GIF twice in one chat
- A user forwards a video to another chat
- Different bots each receive the same image forwarded from a group

This means the same underlying content is always identifiable via `file_unique_id`, regardless of how, where, or by whom it was sent. It is used as the primary cache key for media storage.

## Proposed Architecture — Unified Cache Layer

The three options (A: lazy HTTP proxy, B: eager download + store, C: two-part AMQP) are not alternatives. They converge into a single design:

```text
1. Event arrives → publish to AMQP immediately (always)
                    └─ includes: file_id, file_unique_id, media_status: "pending"
2. In background:
   check config → matches eager pattern?
       Yes → start async download to disk cache (keyed by file_unique_id)
       No  → do nothing (wait for subscriber request)
3. Subscriber needs the file:
   GET /files/{bot_id}/{file_unique_id}
       → disk cache hit?  serve immediately
       → disk cache miss? download from Telegram, write-through to cache, serve
```

Key properties:

- **Event publication never blocks** on download. The subscriber always gets the event immediately.
- **The HTTP endpoint is the single access point** — subscribers don't choose eager or lazy. They request the file; tg-if serves it from cache or fetches it on demand.
- **Eager vs. lazy only controls timing of the first download** — eager triggers on event receipt, lazy triggers on first subscriber request. Both populate the same cache. After the first download, behavior is identical.
- **write-through cache** — every lazy download is cached for subsequent requests, so the same `file_unique_id` is fetched from Telegram exactly once regardless of how many subscribers request it.

### Event Publication

```json
{
  "event_id": "uuid",
  "timestamp": "...",
  "bot_id": "aibot",
  "chat_id": 12345,
  "user_id": 67890,
  "message_id": 100,
  "has_media": true,
  "media_type": "animation",
  "file_id": "AgAC...",
  "file_unique_id": "QQAD...",
  "media_status": "pending",
  "media_url": "http://tg-if:8080/files/aibot/QQAD..."
}
```

`media_url` is always populated — it's a stable endpoint that works whether or not the file has been cached yet. The endpoint resolves on demand.

## Eager vs. Lazy Configuration

The configuration determines which media files are downloaded proactively on event receipt (eager). Everything else defaults to lazy (on-demand).

### Scope levels (highest to lowest precedence)

```text
user > chat > content_type > global default
```

Examples:

- Global: eager for GIFs; for Chat -10012345: eager for nothing → that chat users' GIFs are lazy
- Chat X: eager for all; User Alice: lazy → Alice's media in Chat X is lazy, everyone else's in Chat X is eager
- Global: lazy for everything → the system is pure Option A

### Configuration targets

| Scope | Identifier | Example |
|---|---|---|
| Global | — | eager download: GIF |
| Chat | chat_id | eager download: Chat -10012345, all media |
| User | user_id | eager download: User 67890, GIF + Image + Audio |

### Configuration mechanism

Two channels:

1. **Admin commands** (Telegram DM to admin bot):

   ```text
   /media-eager --scope global --type gif                 # all GIFs eager
   /media-eager --scope chat:-10012345 --type all          # all media in chat eager
   /media-eager --scope user:67890 --type gif,image,audio  # specific user's media eager
   /media-lazy --scope user:67890 --type video             # override: user's videos lazy
   /media-config                                              # show current rules
   ```

2. **Control AMQP queue** `tg-if.media-config` (for subscribers to modify rules at runtime without Telegram access):

   ```json
   Published to tg-if.media-config:
   {
     "action": "eager",
     "scope": "chat:-10012345",
     "type": "gif,image,audio"
   }
   ```

   Tg-if consumes this queue and updates its in-memory config. Persistent storage for rules is a future concern (could use a simple JSON file or a SQLite db).

## HTTP Proxy Endpoint — GET /files/{bot_id}/{file_unique_id}

### Behavior

1. **Check disk cache** by `{file_unique_id}.{ext}` — if exists, stream the file with appropriate `Content-Type`
2. **Cache miss** — use `pyrogram.Client.download_media(file_id, in_memory=True)` to fetch from Telegram, stream response to subscriber, and write through to disk cache asynchronously
3. **Client disconnected** — if subscriber disconnects mid-stream, cancel the download (no wasted bandwidth)

### Error responses

| Status | Condition |
|---|---|
| `200` | File served (from cache or fresh download) |
| `404` | Bot not found or `file_unique_id` not valid |
| `502` | Telegram download failed (Pyrofork error, timeout) |
| `503` | Corresponding Telegram client is disconnected |

### Security

The endpoint exposes no authentication in the initial implementation — access is controlled by network layer (internal network, firewall). Token-based auth can be added later if subscribers are external to the network.

## Storage Management

### On-disk layout

```text
/data/media/{bot_id}/{file_unique_id}.{ext}
```

Example:

```text
/data/media/aibot/QQAD123abc.gif
/data/media/aibot/QQAD456def.jpg
/data/media/supportbot/QQAD789ghi.mp3
```

### Admin commands

**`/media-list`** — Show cached media with configurable sort columns:

```text
/media-list                                # default sort: size desc
/media-list --sort size:asc,accesses:desc,lru:desc
```

| Column | Source |
|---|---|
| `file_unique_id` | From filename |
| `type` | Retrieved from storage metadata or file extension |
| `size` | `os.path.getsize()` |
| `accesses` | Count of times the file was served (in-memory counter) |
| `last_access` | Timestamp of last serve (updated on each hit) |
| `stored_at` | Timestamp when file was first cached |

Example output:

```text
file_unique_id | type | size    | accesses | last_access          | stored_at
QQAD123abc     | gif  | 50 KB   | 5        | 2026-06-15T10:00:00 | 2026-06-14T08:00:00
QQAD456def     | jpg  | 1.2 MB  | 1        | 2026-06-15T09:00:00 | 2026-06-15T09:00:00
QQAD789ghi     | mp3  | 5.5 MB  | 50       | 2026-06-14T18:00:00 | 2026-06-10T12:00:00
QQAD000xyz     | mp4  | 200 MB  | 0        | —                   | 2026-06-13T10:00:00
```

**`/media-prune`** — Prune cache based on sorted list:

```text
/media-prune --keep first:50          # keep top 50, prune rest (based on current sort)
/media-prune --prune first:50         # prune top 50, keep rest
/media-prune --max-size 500MB         # prune oldest until total under 500MB
/media-prune --older-than 7d          # prune files not accessed in 7 days
```

The `--keep first:N` / `--prune first:N` modes respect the current sort order of `/media-list`. So an admin can:

1. Sort by `size:desc` + `accesses:asc` + `lru:asc` to find "large, rarely accessed, old files"
2. Run `/media-prune --keep first:200` to keep the top 200 (smallest, most accessed, newest) and prune the rest

**`/media-purge`** — Delete all cached media. Requires a confirmation step.

**`/media-stats`** — Show aggregate statistics:

```text
total files: 1,234
total size:  850 MB
by type:
  gif:   500 files, 25 MB
  image: 400 files, 200 MB
  audio: 300 files, 500 MB
  video: 34 files,  125 MB
```

### Dedup is natural

Because filenames are `file_unique_id.{ext}`, the same content sent 50 times (same user, multiple chats, forwards) results in **1 download and 1 file on disk**. The cache layer deduplicates automatically.

## Subscriber Contract

### Consuming events

Subscribers receive events as normal from `tg-if.events`. For media messages, the event includes:

- `file_id` — short-lived access token, can be used to call `GET /files/{bot_id}/{file_id}`
- `file_unique_id` — stable content identifier, can be used for local dedup
- `media_status` — `"pending"` (always on first publish)
- `media_url` — endpoint to fetch the actual content

### Status updates (optional)

If eager download completes, tg-if may publish a status update to `tg-if.events`:

```json
{
  "event_type": "media_ready",
  "file_unique_id": "QQAD...",
  "file_id": "AgAC...",
  "media_url": "http://tg-if:8080/files/aibot/QQAD...",
  "original_event_id": "uuid-of-original-event"
}
```

Subscribers can ignore this (just call the endpoint when needed) or use it to know the file is cached without triggering a lazy download.

### Fetching media

```text
GET http://tg-if:8080/files/{bot_id}/{file_unique_id}
```

The endpoint resolves the file regardless of cache state. Response `Content-Type` is derived from the file extension / Telegram media type.

### Configuring media rules (optional)

Publish to `tg-if.media-config`:

```json
{
  "action": "eager",
  "scope": "chat:-10012345",
  "type": "gif,image,audio"
}
```

Or via admin bot DM:

```text
/media-eager --scope chat:-10012345 --type gif,image,audio
```

## Key Decisions

| Decision | Rationale |
|---|---|
| Eager+lazy co-exist, not separate options | Both use the same cache layer; config only controls timing of first download |
| Event published immediately, never blocked on download | Subscriber always receives the event in real time; download latency is moved to the HTTP call |
| HTTP endpoint as single access point | Subscriber doesn't need to know eager/lazy state; one URL always works |
| write-through cache on lazy access | Same `file_unique_id` downloaded once regardless of subscriber count |
| `file_unique_id` as cache/storage key | Natural dedup, stable across forwards and sessions |
| Configurable via admin commands + control AMQP queue | Operators manage via Telegram; subscribers manage via broker; no deployment restart needed |
| Manual pruning via admin commands | Avoids accidental data loss from automatic eviction; admin decides what to keep based on actual usage data |
| No authentication on /files endpoint initially | Network-level security is sufficient for an internal service; can add token auth later if needed |

## Open Questions

1. **Config persistence:** Rules are in-memory on first implementation. Should they persist to a file (JSON, SQLite) so they survive tg-if restarts? Or is re-applying on startup acceptable?

2. **Status updates:** Are `media_ready` status events useful, or noise? Subscribers that need the file will call the HTTP endpoint anyway — the endpoint blocks until ready.

3. **Media types not covered:** Stickers, voice, video notes — should they follow the same pipeline? File size is tiny (stickers are ~10-50KB), so eager makes sense.

4. **Streaming vs. full-buffer:** Currently `download_media(in_memory=True)` loads the entire file into memory before returning. For very large files (>100MB), this is expensive. Could chunk the download and stream, but Pyrofork doesn't support this natively.

5. **File extension mapping:** Telegram media objects don't always have reliable extensions. Do we map by media type (e.g., `animation` → `.gif`, `video` → `.mp4`, `photo` → `.jpg`), or try to extract from the file name in the Telegram message?
