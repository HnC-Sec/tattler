from __future__ import annotations

from typing import Any

from tattler.events import MatchEvent


class DiscordFormatter:
    def format(self, event: MatchEvent, rendered_message: str) -> dict[str, Any]:
        return {"content": rendered_message}
