import asyncio
import signal
import sys

import structlog

from app.log_buffer import LogBuffer
from app.receiver_service import ReceiverService
from infrastructure.config import AppConfig, ConfigLoader


async def main() -> None:
    config: AppConfig | None = ConfigLoader.load()
    if config is None:
        print("Error: Failed to load configuration")
        sys.exit(1)

    log_buffer: LogBuffer = LogBuffer()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            log_buffer.processor,
            structlog.dev.ConsoleRenderer(),
        ],
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()

    service: ReceiverService = ReceiverService(config, log_buffer=log_buffer)
    await service.start()
    logger.info(
        "starting",
        version="0.1.0",
        bots=[b.name for b in config.bots or []],
    )

    stop_event: asyncio.Event = asyncio.Event()
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
