"""Echo Core background worker.

Runs the scheduler tick on a configurable interval.

Start with:
    python -m echo.worker
"""
from __future__ import annotations

import signal
import time

from echo.config import ECHO_ENABLED, WORKER_TICK_INTERVAL
from echo.core.logger import get_logger
from echo.db import create_tables, db_session

# Import workflows to trigger registration
import echo.workflows  # noqa: F401

log = get_logger("echo.worker")

_running = True


def _handle_signal(signum: int, frame: object) -> None:
    global _running
    log.info("Worker received signal %d — shutting down gracefully", signum)
    _running = False


def tick_once() -> None:
    """Run a single scheduler tick inside a database session."""
    from echo.core.scheduler import tick
    with db_session() as db:
        report = tick(db)
    if report.processed > 0 or report.failed > 0:
        log.info(
            "Tick complete: processed=%d failed=%d",
            report.processed,
            report.failed,
        )


def main() -> None:
    if not ECHO_ENABLED:
        log.warning("ECHO_ENABLED is false — worker will run but skip scheduling")

    log.info("Echo Worker starting — tick_interval=%ds", WORKER_TICK_INTERVAL)
    create_tables()

    from echo.core.registry import workflow_count
    log.info("Registered workflows: %d", workflow_count())

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while _running:
        try:
            tick_once()
        except Exception:
            log.exception("Unhandled error in worker tick — continuing")
        for _ in range(WORKER_TICK_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    log.info("Echo Worker stopped")


if __name__ == "__main__":
    main()
