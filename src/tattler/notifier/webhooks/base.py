from __future__ import annotations

from typing import Any, Protocol

from tattler.events import MatchEvent


class WebhookFormatter(Protocol):
    def format(self, event: MatchEvent, rendered_message: str) -> dict[str, Any]:
        ...
