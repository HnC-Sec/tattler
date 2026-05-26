from __future__ import annotations

from typing import Any

from tattler.config.models import GlobalConfig, RuleConfig
from tattler.events import MatchEvent
from tattler.notifier.template import render


class DiscordFormatter:
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        # Temporary: preserved behavior. Task 4 replaces this with embed rendering.
        template = rule.message or (rule.embed.description if rule.embed else "")
        return {"content": render(template, event)}
