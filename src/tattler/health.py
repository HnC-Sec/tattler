from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class HealthFiles:
    def __init__(self, live_path: Path, ready_path: Path) -> None:
        self._live = live_path
        self._ready = ready_path

    async def touch_live(self) -> None:
        self._live.touch(exist_ok=True)
        # bump mtime explicitly
        self._live.write_bytes(b"")

    def mark_ready(self) -> None:
        self._ready.touch(exist_ok=True)

    def mark_unready(self) -> None:
        self._ready.unlink(missing_ok=True)

    async def heartbeat(self, interval_seconds: float = 10.0) -> None:
        while True:
            try:
                await self.touch_live()
            except Exception:
                logger.exception("failed to touch live file")
            await asyncio.sleep(interval_seconds)
