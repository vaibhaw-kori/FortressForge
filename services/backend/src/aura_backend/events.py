"""In-process async event bus (prototype).

Designed to be swappable for Redis pub/sub later without changing call sites.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        for handler in list(self._subs.get(channel, [])):
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 - handlers are isolated
                # Logging happens inside the handler typically.
                pass

    def subscribe(self, channel: str, handler: EventHandler) -> Callable[[], None]:
        self._subs[channel].append(handler)

        def _unsub() -> None:
            if handler in self._subs.get(channel, []):
                self._subs[channel].remove(handler)

        return _unsub


bus = EventBus()