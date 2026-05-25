from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from tattler.config.models import Config, RuleConfig
from tattler.events import MatchEvent


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

    def evaluate(self, msg: MessageView) -> Iterator[MatchEvent]:
        snowflakes = msg.snowflakes()
        global_exclude = set(self._config.globals.exclude)
        global_include = set(self._config.globals.include)
        searchable = msg.searchable_text()

        for rule in self._config.rules:
            if not self._passes_filters(snowflakes, global_include, global_exclude, rule):
                continue
            m = rule.compiled_pattern.search(searchable)
            if m is None:
                continue
            yield MatchEvent(
                rule_name=rule.name,
                rule_webhooks=tuple(rule.webhooks),
                rule_message_template=rule.message,
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
