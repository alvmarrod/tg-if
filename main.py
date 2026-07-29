import asyncio
import signal
from typing import Callable

import structlog

from app.log_buffer import LogBuffer
from app.receiver_service import ReceiverService
from infrastructure.config import AppConfig, ConfigLoader


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

    logger: structlog.types.BoundLogger = structlog.get_logger()  # type: ignore

    config_result = ConfigLoader.load()
    if config_result is None:
        logger.error("config loader returned None")
        raise RuntimeError("Failed to load configuration")
    if not isinstance(config_result, AppConfig):
        logger.error(f"config loader returned unexpected type: {type(config_result)}")
        raise RuntimeError("Failed to load configuration")
    config = config_result

    service: ReceiverService = ReceiverService(config, log_buffer=log_buffer)
    try:
        await service.start()

        logger.info(
            "starting",
            version="0.1.0",
            bots=[b.name for b in config.bots],
        )
    except Exception:
        logger.error("failed to start service", exc_info=True)
        raise

    stop_event: asyncio.Event = asyncio.Event()
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()  # type: ignore
    tasks: list[asyncio.Task] = []  # type: ignore
    sig_tasks: list[asyncio.Task] = []  # type: ignore

    # Create tasks to handle graceful shutdown
    tasks.append(asyncio.create_task(service.stop()))

    for sig in (signal.SIGINT, signal.SIGTERM):
        # Create a new task list for each signal handler to avoid closure issues
        def make_handler(task_list: list[asyncio.Task]) -> Callable[[], None]:
            def handler() -> None:
                # Create task to set stop event and track it
                stop_task = asyncio.create_task(stop_event.set())
                task_list.append(stop_task)

            return handler

        loop.add_signal_handler(sig, make_handler(sig_tasks))

    # Wait for stop event to be set
    await stop_event.wait()
    try:
        # Gather all tasks including signal handler tasks
        await asyncio.gather(*tasks, *sig_tasks, return_exceptions=True)
    except Exception:
        logger.error("failed to stop service", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
