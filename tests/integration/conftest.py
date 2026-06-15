from __future__ import annotations

from collections.abc import Generator

import pytest
from testcontainers.core.container import DockerContainer  # type: ignore[import-untyped]
from testcontainers.core.wait_strategies import (  # type: ignore[import-untyped]
    LogMessageWaitStrategy,
)

from infrastructure.config import BrokerConfig


@pytest.fixture(scope="session")
def rabbitmq_config() -> Generator[BrokerConfig, None, None]:
    container = (
        DockerContainer("rabbitmq:4-alpine")
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    container.start()
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5672)
    try:
        yield BrokerConfig(
            host=host, port=port, user="guest", password="guest", vhost="/"
        )
    finally:
        container.stop()
