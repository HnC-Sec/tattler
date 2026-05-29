from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from tattler.config.models import (
    Config,
    InviteRuleConfig,
    MessageRuleConfig,
    RuleConfig,
)
from tattler.events import MatchEvent
from tattler.invites import InviteView, extract_invite_codes


# Lowercase substrings used by the cheap early-out check before invoking the
# (potentially expensive) invite-code regex / resolver. Matches the host-only
# parts of the invite-extraction regex.
_INVITE_HINTS: tuple[str, ...] = (
    "discord.gg",
    "discord.com/invite",
    "discordapp.com/invite",
)


@dataclass(frozen=True)
class MessageView:
    """Library-agnostic projection of a Discord message used by the matcher."""

    author: str
    author_id: int
    channel_name: str
    channel_id: int
    guild_name: str
    guild_id: int | None
    author_role_ids: tuple[int, ...]
    content: str
    embed_text: str
    attachment_filenames: tuple[str, ...]
    message_id: int
    message_link: str
    timestamp: datetime
    is_edit: bool

    def snowflakes(self) -> set[int]:
        s: set[int] = {self.author_id, self.channel_id}
        if self.guild_id is not None:
            s.add(self.guild_id)
        s.update(self.author_role_ids)
        return s

    def searchable_text(self) -> str:
        parts: list[str] = [self.content, self.embed_text, *self.attachment_filenames]
        return "\n".join(p for p in parts if p)


class Matcher:
    def __init__(self, config: Config) -> None:
        self._config = config

    async def evaluate(
        self,
        msg: MessageView,
        invite_resolver,
    ) -> AsyncIterator[MatchEvent]:
        """Yield a MatchEvent for each rule (message or invite) that matches.

        `invite_resolver` is any object with `async def resolve(code) -> InviteView`.
        It is only consulted when at least one invite rule passes the common
        snowflake filter AND the message content has a Discord-invite-looking
        substring.
        """
        snowflakes = msg.snowflakes()
        global_exclude = set(self._config.globals.exclude)
        global_include = set(self._config.globals.include)
        searchable = msg.searchable_text()

        # Partition rules into message and invite buckets, applying the common
        # snowflake filter (testing where the message was posted) to each.
        passing_message_rules: list[MessageRuleConfig] = []
        passing_invite_rules: list[InviteRuleConfig] = []
        for rule in self._config.rules:
            if not self._passes_filters(
                snowflakes, global_include, global_exclude, rule
            ):
                continue
            if isinstance(rule, MessageRuleConfig):
                passing_message_rules.append(rule)
            else:
                passing_invite_rules.append(rule)

        # --- Message rules -----------------------------------------------------
        for rule in passing_message_rules:
            m = rule.compiled_pattern.search(searchable)
            if m is None:
                continue
            yield MatchEvent(
                rule_name=rule.name,
                rule_webhooks=tuple(rule.webhooks),
                rule_rate_limit_seconds=rule.effective_rate_limit(self._config.globals),
                author=msg.author,
                author_id=msg.author_id,
                channel_name=msg.channel_name,
                channel_id=msg.channel_id,
                guild_name=msg.guild_name,
                guild_id=msg.guild_id,
                content=msg.content,
                message_id=msg.message_id,
                message_link=msg.message_link,
                timestamp=msg.timestamp,
                is_edit=msg.is_edit,
                match=m.group(0),
                match_groups=tuple(g if g is not None else "" for g in m.groups()),
            )

        # --- Invite rules ------------------------------------------------------
        if not passing_invite_rules:
            return

        # Cheap early-out before even running the invite regex / resolver.
        content_lower = msg.content.lower()
        if not any(hint in content_lower for hint in _INVITE_HINTS):
            return

        codes = extract_invite_codes(msg.content)
        if not codes:
            return

        for code in codes:
            view = await invite_resolver.resolve(code)
            for rule in passing_invite_rules:
                event = self._evaluate_invite_rule(rule, view, msg)
                if event is not None:
                    yield event

    def _evaluate_invite_rule(
        self,
        rule: InviteRuleConfig,
        view: InviteView,
        msg: MessageView,
    ) -> MatchEvent | None:
        """Return a MatchEvent if the rule matches the given invite, else None."""
        compiled_pattern = rule.compiled_pattern  # may be None
        match_str = ""
        match_groups: tuple[str, ...] = ()

        if view.resolved:
            # target_guild_include
            if rule.target_guild_include:
                if view.guild_id is None or view.guild_id not in rule.target_guild_include:
                    return None
            # target_guild_exclude
            if rule.target_guild_exclude:
                if view.guild_id is not None and view.guild_id in rule.target_guild_exclude:
                    return None
            # min_members
            if rule.min_members is not None:
                if (
                    view.approximate_member_count is None
                    or view.approximate_member_count < rule.min_members
                ):
                    return None
            # max_members
            if rule.max_members is not None:
                if (
                    view.approximate_member_count is None
                    or view.approximate_member_count > rule.max_members
                ):
                    return None
            # vanity
            if rule.vanity is not None and view.is_vanity != rule.vanity:
                return None
            # has_expiry
            if rule.has_expiry is not None:
                if (view.expires_at is not None) != rule.has_expiry:
                    return None
            # verification_level
            if rule.verification_level:
                if view.verification_level not in rule.verification_level:
                    return None
            # pattern
            if compiled_pattern is not None:
                target = f"{view.guild_name}\n{view.channel_name}\n{view.inviter_name}"
                m = compiled_pattern.search(target)
                if m is None:
                    return None
                match_str = m.group(0)
                match_groups = tuple(g if g is not None else "" for g in m.groups())
        else:
            # Unresolved invite.
            if not rule.match_unresolved:
                return None
            # Only the pattern (matched against the bare code) applies. The
            # config validator guarantees a pattern exists when match_unresolved
            # is true and only resolution-dependent conditions are set, but in
            # any case the pattern is the sole condition evaluated here.
            if compiled_pattern is not None:
                m = compiled_pattern.search(view.code)
                if m is None:
                    return None
                match_str = m.group(0)
                match_groups = tuple(g if g is not None else "" for g in m.groups())
            # If no pattern is set (i.e. validator allowed it because some other
            # unresolved-safe condition was present), the rule simply matches.

        return MatchEvent(
            rule_name=rule.name,
            rule_webhooks=tuple(rule.webhooks),
            rule_rate_limit_seconds=rule.effective_rate_limit(self._config.globals),
            author=msg.author,
            author_id=msg.author_id,
            channel_name=msg.channel_name,
            channel_id=msg.channel_id,
            guild_name=msg.guild_name,
            guild_id=msg.guild_id,
            content=msg.content,
            message_id=msg.message_id,
            message_link=msg.message_link,
            timestamp=msg.timestamp,
            is_edit=msg.is_edit,
            match=match_str,
            match_groups=match_groups,
            invite=view,
        )

    @staticmethod
    def _passes_filters(
        snowflakes: set[int],
        global_include: set[int],
        global_exclude: set[int],
        rule: RuleConfig,
    ) -> bool:
        effective_exclude = global_exclude | set(rule.exclude)
        if snowflakes & effective_exclude:
            return False
        effective_include = global_include | set(rule.include)
        if effective_include and not (snowflakes & effective_include):
            return False
        return True
