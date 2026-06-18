# Backlog

## Work Items

### B-008: Bot command registration channel via AMQP

**Status:** done  
**Area:** infra  
**Subsystem:** [app](doc/subsystems/app.md), [infra](doc/subsystems/infra.md)  
**HLD:** [Architecture § AMQP Topology](doc/architecture_overview.md#amqp-topology)

**Context:** Subscribers need to register their bot commands for Telegram's bot command menu. Each subscriber publishes a one-time registration message on a dedicated channel. tg-if merges registrations across subscribers and calls `set_bot_commands` on the Telegram client.

**Changes:**

- `BotCommandRegistry` — in-memory merge with conflict detection (same command name from two subscribers → NOK response)
- `SubscriberCommandHandler` — validates AMQP envelope, dispatches to registry, calls `set_bot_commands` on success, publishes reply to `reply_to` queue
- `Consumer` refactor — added `routing_key` parameter, removed hardcoded `if/elif` bindings
- Topology: new `subscriber-commands` queue bound to `tg-if.responses` with routing key `"subscriber-commands"`

**Acceptance criteria:**

- Subscriber publishes `{"action": "register", ...}` → commands merged, `set_bot_commands` called
- Conflict when two subscribers register same command → NOK response with details
- Subscriber deregisters → commands removed, `set_bot_commands` called with remaining
- Reply published to `reply_to` queue if provided
- 13 unit tests (registry) + 6 unit tests (handler) + 1 integration test
