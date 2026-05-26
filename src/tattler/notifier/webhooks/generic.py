from __future__ import annotations

from typing import Any

from tattler.config.models import GlobalConfig, RuleConfig
from tattler.events import MatchEvent
from tattler.notifier.template import render


class GenericFormatter:
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        template = rule.message
        if template is None:
            # Validator on RuleConfig guarantees embed.description is set when message is None.
            template = rule.embed.description  # type: ignore[union-attr]
        rendered = render(template, event)
        return {
            "rule_name": event.rule_name,
            "message": rendered,
            "event": {
                "author": event.author,
                "author_id": str(event.author_id),
                "channel_name": event.channel_name,
                "channel_id": str(event.channel_id),
                "guild_name": event.guild_name,
                "guild_id": "" if event.guild_id is None else str(event.guild_id),
                "content": event.content,
                "message_id": str(event.message_id),
                "message_link": event.message_link,
                "timestamp": event.timestamp.isoformat(),
                "match": event.match,
                "match_groups": list(event.match_groups),
                "is_edit": event.is_edit,
            },
        }
