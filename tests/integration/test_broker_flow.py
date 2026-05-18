import pytest

pytestmark = pytest.mark.skip(reason="requires running RabbitMQ instance")


class TestBrokerFlow:
    async def test_publish_and_consume(self) -> None:
        pass

    async def test_consumer_retry_round_trip(self) -> None:
        pass
