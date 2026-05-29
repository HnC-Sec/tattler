from __future__ import annotations

import string

from tattler.events import MatchEvent


class _SafeMapping(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _event_values(event: MatchEvent) -> dict[str, str]:
    values: dict[str, str] = {
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
    invite = event.invite
    if invite is not None:
        values.update(
            {
                "invite_code": invite.code,
                "invite_resolved": str(invite.resolved),
                "invite_guild_id": "" if invite.guild_id is None else str(invite.guild_id),
                "invite_guild_name": invite.guild_name,
                "invite_channel_id": "" if invite.channel_id is None else str(invite.channel_id),
                "invite_channel_name": invite.channel_name,
                "invite_inviter_id": "" if invite.inviter_id is None else str(invite.inviter_id),
                "invite_inviter_name": invite.inviter_name,
                "invite_member_count": (
                    ""
                    if invite.approximate_member_count is None
                    else str(invite.approximate_member_count)
                ),
                "invite_presence_count": (
                    ""
                    if invite.approximate_presence_count is None
                    else str(invite.approximate_presence_count)
                ),
                "invite_expires_at": (
                    "" if invite.expires_at is None else invite.expires_at.isoformat()
                ),
                "invite_is_vanity": str(invite.is_vanity),
                "invite_verification_level": invite.verification_level,
            }
        )
    return values


def render(template: str, event: MatchEvent) -> str:
    return string.Formatter().vformat(template, (), _SafeMapping(_event_values(event)))
