from __future__ import annotations

from typing import Any, Protocol

from tattler.config.models import GlobalConfig, RuleConfig
from tattler.events import MatchEvent


class WebhookFormatter(Protocol):
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        ...
