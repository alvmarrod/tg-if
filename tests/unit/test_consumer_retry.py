from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.broker import Consumer


@pytest.fixture
def callback() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def on_failed() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def consumer(callback: AsyncMock, on_failed: AsyncMock) -> Consumer:
    manager = MagicMock()
    return Consumer(
        manager=manager,
        queue_name="test_queue",
        callback=callback,
        max_retries=2,
        on_failed=on_failed,
    )


class TestConsumerRetry:
    async def test_first_try_succeeds(
        self, consumer: Consumer, callback: AsyncMock, on_failed: AsyncMock
    ) -> None:
        body = {"key": "value"}
        callback.return_value = None

        await consumer._call_with_retry(body)

        callback.assert_awaited_once_with(body)
        on_failed.assert_not_awaited()

    async def test_retry_then_succeeds(
        self, consumer: Consumer, callback: AsyncMock, on_failed: AsyncMock
    ) -> None:
        body = {"key": "value"}
        callback.side_effect = [ValueError("first fail"), None]

        await consumer._call_with_retry(body)

        assert callback.await_count == 2
        on_failed.assert_not_awaited()

    async def test_all_retries_fail_calls_on_failed(
        self, consumer: Consumer, callback: AsyncMock, on_failed: AsyncMock
    ) -> None:
        body = {"key": "value"}
        exc = ValueError("always fail")
        callback.side_effect = exc

        await consumer._call_with_retry(body)

        assert callback.await_count == 3
        on_failed.assert_awaited_once_with(body, exc)

    async def test_on_failed_callback_failure_does_not_crash(
        self,
        consumer: Consumer,
        callback: AsyncMock,
        on_failed: AsyncMock,
    ) -> None:
        body = {"key": "value"}
        callback.side_effect = ValueError("fail")
        on_failed.side_effect = RuntimeError("on_failed crash")

        await consumer._call_with_retry(body)

        assert callback.await_count == 3

    async def test_max_retries_zero(
        self, callback: AsyncMock, on_failed: AsyncMock
    ) -> None:
        manager = MagicMock()
        zero_consumer = Consumer(
            manager=manager,
            queue_name="test_queue",
            callback=callback,
            max_retries=0,
            on_failed=on_failed,
        )
        body = {"key": "value"}
        exc = ValueError("fail once")
        callback.side_effect = exc

        await zero_consumer._call_with_retry(body)

        callback.assert_awaited_once_with(body)
        on_failed.assert_awaited_once_with(body, exc)

    async def test_no_on_failed_does_not_crash(
        self, consumer: Consumer, callback: AsyncMock
    ) -> None:
        consumer_no_fail = Consumer(
            manager=MagicMock(),
            queue_name="test_queue",
            callback=callback,
            max_retries=1,
        )
        body = {"key": "value"}
        callback.side_effect = ValueError("fail")

        await consumer_no_fail._call_with_retry(body)

        assert callback.await_count == 2
