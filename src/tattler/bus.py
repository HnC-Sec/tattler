from __future__ import annotations

import asyncio

from tattler.events import MatchEvent


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[MatchEvent] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, event: MatchEvent) -> None:
        await self._queue.put(event)

    async def get(self) -> MatchEvent:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def qsize(self) -> int:
        return self._queue.qsize()
