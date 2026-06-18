# Acceptance Criteria — B-009

## AC1: TelegramClient.edit_message_text exists and calls Pyrofork edit_message_text

- **Pass:** Method takes `chat_id`, `message_id`, `text`, optional `parse_mode` and `reply_markup`; calls `self._client.edit_message_text()` with correct args; returns `Message`.
- **Fail:** Method missing, signature wrong, or delegates to wrong Pyrofork call.

## AC2: TelegramClient.answer_callback_query exists and calls Pyrofork answer_callback_query

- **Pass:** Method takes `callback_query_id`, optional `text`, `show_alert`, `url`, `cache_time`; calls `self._client.answer_callback_query()` with correct args; returns `bool`.
- **Fail:** Method missing, signature wrong, or delegates to wrong Pyrofork call.

## AC3: ResponseConsumer dispatches edit_message_text with chat_id + payload kwargs

- **Pass:** Submitting `response_type="edit_message_text"` with payload containing `message_id` and `text` calls `client.edit_message_text(chat_id=..., message_id=..., text=...)`.
- **Fail:** Method not called, or called with wrong args.

## AC4: ResponseConsumer dispatches answer_callback_query without chat_id

- **Pass:** Submitting `response_type="answer_callback_query"` with payload containing `callback_query_id` calls `client.answer_callback_query(callback_query_id=...)`. The `chat_id` from `OutgoingResponse` is **not** passed.
- **Fail:** `chat_id` is passed to `answer_callback_query`, or method is not called.

## AC5: Existing send methods continue to work unchanged

- **Pass:** All 6 existing `send_*` methods are dispatched with `chat_id` + payload kwargs as before.
- **Fail:** Any existing method breaks or changes its arg contract.

## AC6: OutgoingResponse.response_type docstring mentions both new types

- **Pass:** Docstring at `entities.py:154` includes `"edit_message_text"` and `"answer_callback_query"`.
- **Fail:** Docstring unchanged.
