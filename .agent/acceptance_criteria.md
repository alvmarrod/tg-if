# Acceptance Criteria — B-008

## AC1: BotCommandRegistry.register merges commands from multiple subscribers

**Pass:** Two subscribers register different commands for same bot → `get_commands` returns flat list with both.
**Fail:** Commands not merged or lost.

## AC2: BotCommandRegistry detects conflicts

**Pass:** Two subscribers register the same command name → `status: "nok"` with conflict details.
**Fail:** Conflict allowed without error, or wrong subscriber blamed.

## AC3: BotCommandRegistry.deregister removes subscriber's commands

**Pass:** After deregister, `get_commands` no longer includes that subscriber's commands.
**Fail:** Commands persist after deregister, or other subscriber's commands removed.

## AC4: SubscriberCommandHandler calls set_bot_commands on successful register

**Pass:** Register message processed → `client.set_bot_commands` called with merged list.
**Fail:** `set_bot_commands` not called, or called with wrong args.

## AC5: Conflict does not call set_bot_commands

**Pass:** Register with conflict → handler responds NOK, `set_bot_commands` not called.
**Fail:** `set_bot_commands` called despite conflict.

## AC6: SubscriberCommandHandler publishes reply on reply_to queue

**Pass:** When `reply_to` is set, a `SubscriberCommandResponse` is published to that queue.
**Fail:** No reply published, or reply has wrong format.

## AC7: Consumer accepts optional routing_key parameter

**Pass:** Consumer with `routing_key="test"` binds queue to exchange. Consumer without `routing_key` does not bind.
**Fail:** Consumer always binds, or never binds, regardless of parameter.

## AC8: Integration test: register command via subscriber-commands queue

**Pass:** Publish register message → consumer receives it on subscriber-commands routing key.
**Fail:** Message not delivered, or delivered to wrong routing key.
