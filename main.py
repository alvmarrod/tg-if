import asyncio
import signal

import structlog

from app.log_buffer import LogBuffer
from app.receiver_service import ReceiverService
from infrastructure.config import ConfigLoader
from infrastructure.version import get_version


async def main() -> None:
    """Main entry point for the application."""
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

    config = ConfigLoader.load()
    service: ReceiverService = ReceiverService(config, log_buffer=log_buffer)
    try:
        await service.start()

        logger.info(
            "starting",
            version=get_version(),
            bots=[b.name for b in config.bots],
        )
    except Exception:
        logger.error("failed to start service", exc_info=True)
        raise

    stop_event: asyncio.Event = asyncio.Event()
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.remove_signal_handler(sig)

    await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
