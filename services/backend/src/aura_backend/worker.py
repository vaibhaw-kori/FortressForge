"""Standalone worker entrypoint.

For the prototype the worker is co-located with the API; this entrypoint
is kept so operators can run a dedicated worker process against the same
DB + queue when scaling out.
"""

from __future__ import annotations

import asyncio

from .config import get_settings
from .db import init_db
from .inference.worker import get_worker
from .logging import configure_logging, get_logger


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    log = get_logger("aura.worker_entry")
    log.info("worker_entry_start", env=s.env)
    init_db()
    worker = get_worker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()