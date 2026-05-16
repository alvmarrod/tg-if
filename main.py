import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog

from infrastructure.broker import RabbitMQManager
from infrastructure.config import ConfigLoader
from infrastructure.health import create_health_server


async def main() -> None:
    config = ConfigLoader.load()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()

    broker = RabbitMQManager(config.broker)
    await broker.connect()

    await create_health_server(config.health_port, broker=broker)
    logger.info("starting", version="0.1.0", bots=[b.name for b in config.bots])

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
