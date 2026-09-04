"""Queue abstraction.

The async job pipeline needs a queue that:
- accepts GenerationJob IDs
- exposes async `get` and `ack`/`fail` semantics
- supports cancel
- is replaceable with BullMQ/Redis in production via the same interface.

The prototype ships an in-process asyncio queue (`InMemoryQueue`). It is
safe to run multiple workers in the same process against it; not safe
across processes — production wires `RedisQueue` against BullMQ.
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from ..logging import get_logger

log = get_logger("aura.queue")


class JobQueue(ABC):
    """Abstract queue."""

    @abstractmethod
    async def put(self, job_id: str, priority: int = 0) -> None: ...

    @abstractmethod
    async def get(self, timeout: float | None = None) -> str | None:
        """Block until a job is available or timeout expires.

        Returns the job_id or None on timeout.
        """

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Mark a queued job as cancelled. Returns True if it was queued."""

    @abstractmethod
    async def join(self) -> None: ...

    @abstractmethod
    def qsize(self) -> int: ...

    @abstractmethod
    def stats(self) -> dict[str, Any]: ...


class InMemoryQueue(JobQueue):
    """asyncio-backed FIFO queue with priority support + cancel tracking."""

    def __init__(self, maxsize: int = 0) -> None:
        # priority queue (lower number = higher priority).
        self._queue: asyncio.PriorityQueue[tuple[int, int, str]] = asyncio.PriorityQueue(
            maxsize=maxsize
        )
        self._cancelled: set[str] = set()
        self._seq = 0
        self._lock = asyncio.Lock()
        self._stats_total = 0

    async def put(self, job_id: str, priority: int = 0) -> None:
        async with self._lock:
            self._seq += 1
            self._stats_total += 1
        await self._queue.put((priority, self._seq, job_id))
        log.debug("queue_put", job_id=job_id, priority=priority)

    async def get(self, timeout: float | None = None) -> str | None:
        try:
            if timeout is None:
                _, _, job_id = await self._queue.get()
            else:
                _, _, job_id = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if job_id in self._cancelled:
            self._cancelled.discard(job_id)
            self._queue.task_done()
            return None
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued job (before a worker picks it up)."""
        if job_id in self._cancelled:
            return False
        self._cancelled.add(job_id)
        return True

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    async def join(self) -> None:
        await self._queue.join()

    def qsize(self) -> int:
        return self._queue.qsize()

    def task_done(self) -> None:
        with contextlib.suppress(ValueError):
            self._queue.task_done()

    def stats(self) -> dict[str, Any]:
        return {
            "size": self._queue.qsize(),
            "cancelled": len(self._cancelled),
            "total_enqueued": self._stats_total,
        }


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = InMemoryQueue()
    return _queue


def set_queue(queue: JobQueue) -> None:
    """Override the global queue (used by tests)."""
    global _queue
    _queue = queue


async def iter_jobs(timeout: float = 1.0) -> AsyncIterator[str]:
    """Async iterator over job IDs. Yields None on timeout to allow checks."""
    q = get_queue()
    while True:
        job_id = await q.get(timeout=timeout)
        if job_id is None:
            yield None  # heartbeat
            continue
        yield job_id
        q.task_done()