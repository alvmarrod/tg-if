# Backlog

## Work Items

### B-008: General subscriber command channel via AMQP

**Status:** pending  
**Area:** infra  
**Subsystem:** [app](doc/subsystems/app.md), [infra](doc/subsystems/infra.md)  
**HLD:** [Architecture § AMQP Topology](doc/architecture_overview.md#amqp-topology)

**Context:** Subscribers can currently send responses (`outgoing.responses`) and media-config rules (`media-config`) to tg-if via AMQP, but there is no general-purpose command channel. Operations like `/status`, `/rule-add`, `/shutdown`, `/bots`, `/log`, etc. are admin-bot-only via Telegram DM.

**Goal:** Add a `subscriber-commands` routing key (bound to `tg-if.responses` exchange) that accepts a generic command model. The handler dispatches similarly to `AdminCommandHandler`, giving subscribers programmatic access to routing rules, lifecycle, metrics, and logs without needing Telegram access.

**Acceptance criteria:**

- New `SubscriberCommand` Pydantic model (action + args)
- New consumer on `subscriber-commands` key bound to `tg-if.responses`
- Handler dispatches to existing `AdminCommandHandler`-compatible methods
- At minimum: `/status`, `/rule-add`, `/rule-remove`, `/shutdown` commands work via AMQP
- Existing admin-bot commands continue to work unchanged
- Tests for the new consumer + handler dispatch
