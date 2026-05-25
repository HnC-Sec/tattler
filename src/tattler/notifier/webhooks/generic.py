from __future__ import annotations

from typing import Any

from tattler.events import MatchEvent


class GenericFormatter:
    def format(self, event: MatchEvent, rendered_message: str) -> dict[str, Any]:
        return {
            "rule_name": event.rule_name,
            "message": rendered_message,
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
