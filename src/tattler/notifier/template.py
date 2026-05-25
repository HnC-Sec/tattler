from __future__ import annotations

import string

from tattler.events import MatchEvent


class _SafeMapping(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _event_values(event: MatchEvent) -> dict[str, str]:
    return {
        "rule_name": event.rule_name,
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
        "match_groups": ",".join(event.match_groups),
        "is_edit": str(event.is_edit),
    }


def render(template: str, event: MatchEvent) -> str:
    return string.Formatter().vformat(template, (), _SafeMapping(_event_values(event)))
