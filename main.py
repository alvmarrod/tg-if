import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog

from app.receiver_service import ReceiverService
from infrastructure.config import ConfigLoader


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

    service = ReceiverService(config)
    await service.start()
    logger.info("starting", version="0.1.0", bots=[b.name for b in config.bots])

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
