import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog

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
    logger.info("starting", version="0.1.0", bots=[b.name for b in config.bots])
    await create_health_server(config.health_port)
    logger.info("health server started", port=config.health_port)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
