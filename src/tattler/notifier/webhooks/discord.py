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
        template = rule.message
        if template is None:
            # Validator on RuleConfig guarantees embed.description is set when message is None.
            template = rule.embed.description  # type: ignore[union-attr]
        return {"content": render(template, event)}
