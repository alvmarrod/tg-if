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

### B-009: Support edit_message_text and answer_callback_query in ResponseConsumer

**Status:** pending  
**Area:** app/infra  
**Subsystem:** [app](doc/subsystems/app.md), [infra](doc/subsystems/infra.md)  
**HLD:** [Architecture § Outgoing Response Schema](doc/architecture_overview.md#outgoing-response-schema)

**Context:** The `ResponseConsumer` currently dispatches `response_type` → `send_{type}` on `TelegramClient`. This covers 6 send methods (text, photo, video, document, audio, media_group) but not callback-specific operations. Subscribers handling inline keyboard interactions need `edit_message_text` (update the message text/markup) and `answer_callback_query` (show a toast notification to the user).

**Goal:** Add `edit_message_text` and `answer_callback_query` response types so subscribers can handle the full callback lifecycle without workarounds.

**Implementation:**

- **`src/infrastructure/telegram/client.py`** — add two methods:

  ```python
  async def edit_message_text(
      self, chat_id, message_id, text, parse_mode=None, reply_markup=None
  ) -> Message

  async def answer_callback_query(
      self, callback_query_id, text=None, show_alert=False, url=None, cache_time=0
  ) -> bool
  ```

- **`src/domain/entities.py`** — update `OutgoingResponse.response_type` docstring to include `"edit_message_text"` and `"answer_callback_query"`

- **`src/app/response_consumer.py`** — make the dispatch call flexible so `answer_callback_query` can pass `callback_query_id` instead of `chat_id`. Cleanest approach: drop `chat_id` from the dispatch call entirely and have subscribers include all params (including `chat_id` for send methods) in `payload`:

  ```python
  await method(**response.payload)
  ```

  This simplifies the contract to "payload keys = method kwargs" for all response types. If changing the contract for existing 6 types is a concern, use a `response_type` switch instead.

- **`tests/`** — add unit tests for the two new methods on `TelegramClient` and the updated dispatch in `ResponseConsumer`

**Acceptance criteria:**

- Subscriber publishes `{"response_type": "edit_message_text", "payload": {"chat_id": ..., "message_id": ..., "text": ...}}` → message edited via Pyrofork
- Subscriber publishes `{"response_type": "answer_callback_query", "payload": {"callback_query_id": ..., "text": "Done!"}}` → toast shown to user
- Existing send methods (`text`, `photo`, `video`, etc.) continue working unchanged
- Dispatch handles missing `chat_id` gracefully for the two new types
- Tests for both new methods on `TelegramClient` (mocked Pyrofork)
- Test for `ResponseConsumer` dispatch with the new types
