from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from tattler.invites import InviteView


@dataclass(frozen=True)
class MatchEvent:
    """Emitted by the matcher when a rule matches a message."""

    rule_name: str
    rule_webhooks: tuple[str, ...]
    rule_rate_limit_seconds: int

    # Discord context
    author: str
    author_id: int
    channel_name: str
    channel_id: int
    guild_name: str
    guild_id: int | None
    content: str
    message_id: int
    message_link: str
    timestamp: datetime
    is_edit: bool

    # Match data
    match: str
    match_groups: tuple[str, ...] = field(default_factory=tuple)

    # Populated only for invite-rule matches; None for message-rule matches.
    invite: InviteView | None = None
