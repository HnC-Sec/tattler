from __future__ import annotations

import time
from collections.abc import Callable


class RateLimiter:
    """In-memory cooldown tracker keyed by (rule_name, channel_id)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_fired: dict[tuple[str, int], float] = {}

    def allow(self, rule_name: str, channel_id: int, cooldown: int) -> bool:
        if cooldown <= 0:
            return True
        key = (rule_name, channel_id)
        now = self._clock()
        last = self._last_fired.get(key)
        if last is not None and (now - last) < cooldown:
            return False
        self._last_fired[key] = now
        return True
