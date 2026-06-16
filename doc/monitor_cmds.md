# Admin Monitor Commands

## Overview

The admin bot (dedicated Telegram bot with its own session) responds to DM commands from a configured `user_id`. Responses are sent as new messages (not replies).

| Command | Description |
|---------|-------------|
| `/ping` | Liveness check — returns `pong` |
| `/status` | Control panel: connections, per-bot events, target metrics, media cache, config count |
| `/target <name>` | Detail for a specific routing target |
| `/rule-add --bot <n> --target <key> [--condition k=v ...]` | Append routing rule + persist snapshot |
| `/rule-remove --bot <n> --index <i>` | Remove routing rule by 1-based index + persist snapshot |
| `/shutdown` | Graceful stop of all components |

## `/status` — Control Panel

Full formatted output:

```text
📊 Service Control Panel

⏱️ Uptime: 2h 15m 30s

🔌 Connections:
  broker       ✅   admin        ✅
  aibot        ✅   photobot     ✅

📥 Event Summary (last 1h):
  aibot:      152 recv → 150 match → 148 publish
  photobot:    89 recv →  80 match →  78 publish

📤 Outgoing Responses:
  consumed: 218 → sent: 215 → failed: 3

🎯 Active Targets (last 1h):
  alerts:          98 events  (42.3%)
  conversations:   42 events  (18.1%)
  media:           21 events  (9.1%)
  3 more…          71 events  (30.5%)

🗄️ Media Cache:  142 files (2.3 GB)

🎚️ Config Rules: 4 active
```

### Sections

| Section | Data source | Notes |
|---------|-------------|-------|
| Uptime | `ServiceMetrics.started_at` | Time since service start |
| Connections | `RabbitMQManager.health()`, `TelegramClient.health()` | One row per bot + admin |
| Event Summary | `ServiceMetrics.bot_events` | Per-bot counters, current hour |
| Outgoing Responses | `ServiceMetrics.responses` | Aggregate counters |
| Active Targets | `ServiceMetrics.per_target` | Top 5 by count, rest collapsed |
| Media Cache | `DiskStorage.stats()` | Omitted if no media config |
| Config Rules | `EventDispatcher.get_rules()` | Total rules across all bots |

## `/target <name>` — Per-Target Detail

Shows statistics for a single routing target:

```text
🎯 Target: alerts
  Events (last 1h):  98  (42.3% of total)
  Last event:        14:32:18 (12s ago)
  Published by:      aibot (rule #2), photobot (rule #1)
```

| Field | Source |
|-------|--------|
| Events (last 1h) | `ServiceMetrics.per_target[name].events` |
| Share % | `events / total_events * 100` |
| Last event | `TargetMetrics.last_event` |
| Published by | Resolved from dispatcher rules matching target |

## Target Metrics — Rolling Hour Window

Tracked in `ServiceMetrics`:

```python
@dataclass
class TargetMetrics:
    events: int = 0
    last_event: datetime | None = None

class ServiceMetrics:
    per_target: dict[str, TargetMetrics]
    target_window_start: datetime
```

- Incremented by `EventDispatcher` after each publish (`metrics.target_event(bot_id, target)`)
- Window is cleared when the hour ticks (comparison: `now - window_start >= 3600s`)
- Sorted descending by count for display

### Collapsed display logic

| Total targets | Display |
|---------------|---------|
| ≤ 5 | All shown individually |
| > 5 | Top 5 shown + "N more… M events (P%)" |

## Snapshot Persistence

On each `/rule-add` or `/rule-remove`, the service writes a full rules snapshot to the config directory:

```text
config/
├── bots.json                # Seed file (read at startup)
├── bots_20260615_140615.json
├── bots_20260615_140659.json
└── bots_20260615_140701.json
```

Format matches `bots.json` structure so snapshots can serve as seed files for restore.

```json
{
  "bots": [
    {
      "name": "aibot",
      "api_id": 12345,
      "api_hash": "abc…",
      "session_file": "sessions/aibot.session",
      "routing_rules": [
        {"condition": {"event_type": "message"}, "target": "alerts"}
      ]
    }
  ],
  "admin": null
}
```

The config directory should be a Docker bind mount to enable host-level backup.

## `/shutdown` — Graceful Stop

Sequence:

1. Reply `"Shutting down…"` to admin
2. `ReceiverService.stop()`:
   - Stop health server
   - Cancel health monitor task
   - Stop all Telegram clients
   - Stop admin notifier
   - Stop consumers (media-config + response)
   - Disconnect RabbitMQ
3. `sys.exit(0)`

## Future: RabbitMQ Management API (Path B)

The current implementation (Path A) only knows about routing targets — the keys tg-if produces. It **cannot** enumerate subscriber queues or their bindings.

With RabbitMQ Management HTTP API (port 15672), Path B would add:

| Command | What it shows | Requires |
|---------|--------------|----------|
| `/queues` | List all subscriber queues with bindings | `GET /api/queues` |
| `/queue <name>` | A queue's detail + all its bindings | `GET /api/queues/{vhost}/{name}` |
| `/binding <name>` | All queues matching a binding pattern | `GET /api/bindings` |

To enable Path B:

- Add `RABBITMQ_MANAGEMENT_PORT` (default `15672`) to `BrokerConfig`
- Add RabbitMQ management credentials (usually same as AMQP)
- Integrate a new `RabbitMQInspector` using `aiohttp` to call the management API
- The RabbitMQ server must have the `rabbitmq_management` plugin enabled

**Decision: Path A.** Queue/binding introspection deferred until the management API integration is justified.
