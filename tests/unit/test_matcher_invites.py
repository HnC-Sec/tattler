from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tattler.config.models import Config
from tattler.invites import InviteView
from tattler.matcher import Matcher, MessageView


class _FakeResolver:
    """Duck-typed InviteResolver for tests. Returns canned views from a dict."""

    def __init__(self, views: dict[str, InviteView] | None = None) -> None:
        self.views = views or {}
        self.calls: list[str] = []

    async def resolve(self, code: str) -> InviteView:
        self.calls.append(code)
        if code in self.views:
            return self.views[code]
        # Default: unresolved view for unknown codes
        return InviteView(code=code, resolved=False)


class _ExplodingResolver:
    """Resolver that raises if called — used to prove no resolution happened."""

    async def resolve(self, code: str) -> InviteView:
        raise NotImplementedError(
            f"resolver should not have been called (got code={code!r})"
        )


def _msg(**overrides) -> MessageView:
    defaults = dict(
        author="alice",
        author_id=1,
        channel_name="general",
        channel_id=2,
        guild_name="srv",
        guild_id=3,
        author_role_ids=(),
        content="",
        embed_text="",
        attachment_filenames=(),
        message_id=4,
        message_link="https://discord.com/x",
        timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
        is_edit=False,
    )
    defaults.update(overrides)
    return MessageView(**defaults)


def _resolved_view(
    code: str = "abc123",
    *,
    guild_id: int | None = 100,
    guild_name: str = "Cool Server",
    channel_name: str = "welcome",
    inviter_name: str = "owner",
    approximate_member_count: int | None = 50,
    expires_at: datetime | None = None,
    is_vanity: bool = False,
    verification_level: str = "low",
) -> InviteView:
    return InviteView(
        code=code,
        resolved=True,
        guild_id=guild_id,
        guild_name=guild_name,
        channel_name=channel_name,
        inviter_name=inviter_name,
        approximate_member_count=approximate_member_count,
        expires_at=expires_at,
        is_vanity=is_vanity,
        verification_level=verification_level,
    )


def _cfg(
    *,
    rule_extras: dict | None = None,
    globals_: dict | None = None,
    extra_rules: list[dict] | None = None,
) -> Config:
    rule: dict = {
        "name": "inv1",
        "type": "invite",
        "include": [],
        "exclude": [],
        "message": "invite {invite_code}",
        "webhooks": ["alerts"],
    }
    if rule_extras:
        rule.update(rule_extras)
    base = {
        "globals": globals_
        or {"include": [], "exclude": [], "default_rate_limit_seconds": 30},
        "webhooks": {"alerts": {"url": "https://x", "format": "generic"}},
        "rules": [rule] + (extra_rules or []),
    }
    return Config.model_validate(base)


# -- target_guild_include / target_guild_exclude --------------------------------


async def test_target_guild_include_hit():
    cfg = _cfg(rule_extras={"target_guild_include": [100]})
    resolver = _FakeResolver({"abc": _resolved_view("abc", guild_id=100)})
    msg = _msg(content="check this https://discord.gg/abc")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert len(events) == 1
    assert events[0].rule_name == "inv1"
    assert events[0].invite is not None
    assert events[0].invite.code == "abc"


async def test_target_guild_include_miss():
    cfg = _cfg(rule_extras={"target_guild_include": [999]})
    resolver = _FakeResolver({"abc": _resolved_view("abc", guild_id=100)})
    msg = _msg(content="https://discord.gg/abc")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert events == []


async def test_target_guild_exclude_hit_blocks():
    cfg = _cfg(rule_extras={"target_guild_exclude": [100]})
    resolver = _FakeResolver({"abc": _resolved_view("abc", guild_id=100)})
    msg = _msg(content="https://discord.gg/abc")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert events == []


async def test_target_guild_exclude_miss_allows():
    cfg = _cfg(rule_extras={"target_guild_exclude": [999]})
    resolver = _FakeResolver({"abc": _resolved_view("abc", guild_id=100)})
    msg = _msg(content="https://discord.gg/abc")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert len(events) == 1


# -- min_members / max_members --------------------------------------------------


async def test_min_members_hit():
    cfg = _cfg(rule_extras={"min_members": 10})
    resolver = _FakeResolver({"abc": _resolved_view("abc", approximate_member_count=50)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


async def test_min_members_miss():
    cfg = _cfg(rule_extras={"min_members": 100})
    resolver = _FakeResolver({"abc": _resolved_view("abc", approximate_member_count=50)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_max_members_hit():
    cfg = _cfg(rule_extras={"max_members": 100})
    resolver = _FakeResolver({"abc": _resolved_view("abc", approximate_member_count=50)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


async def test_max_members_miss():
    cfg = _cfg(rule_extras={"max_members": 10})
    resolver = _FakeResolver({"abc": _resolved_view("abc", approximate_member_count=50)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_min_members_none_count_is_miss():
    cfg = _cfg(rule_extras={"min_members": 10})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", approximate_member_count=None)}
    )
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_max_members_none_count_is_miss():
    cfg = _cfg(rule_extras={"max_members": 10})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", approximate_member_count=None)}
    )
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


# -- vanity ---------------------------------------------------------------------


async def test_vanity_true_hit():
    cfg = _cfg(rule_extras={"vanity": True})
    resolver = _FakeResolver({"abc": _resolved_view("abc", is_vanity=True)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


async def test_vanity_true_miss():
    cfg = _cfg(rule_extras={"vanity": True})
    resolver = _FakeResolver({"abc": _resolved_view("abc", is_vanity=False)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_vanity_false_hit():
    cfg = _cfg(rule_extras={"vanity": False})
    resolver = _FakeResolver({"abc": _resolved_view("abc", is_vanity=False)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


# -- has_expiry -----------------------------------------------------------------


async def test_has_expiry_true_hit():
    cfg = _cfg(rule_extras={"has_expiry": True})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc))}
    )
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


async def test_has_expiry_true_miss():
    cfg = _cfg(rule_extras={"has_expiry": True})
    resolver = _FakeResolver({"abc": _resolved_view("abc", expires_at=None)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_has_expiry_false_hit():
    cfg = _cfg(rule_extras={"has_expiry": False})
    resolver = _FakeResolver({"abc": _resolved_view("abc", expires_at=None)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


# -- verification_level ---------------------------------------------------------


async def test_verification_level_hit():
    cfg = _cfg(rule_extras={"verification_level": ["none", "low"]})
    resolver = _FakeResolver({"abc": _resolved_view("abc", verification_level="low")})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


async def test_verification_level_miss():
    cfg = _cfg(rule_extras={"verification_level": ["none", "low"]})
    resolver = _FakeResolver({"abc": _resolved_view("abc", verification_level="high")})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


# -- pattern --------------------------------------------------------------------


async def test_pattern_matches_against_guild_channel_inviter_join():
    cfg = _cfg(rule_extras={"pattern": r"(?s)NitroServer\nwelcome\nowner"})
    resolver = _FakeResolver(
        {
            "abc": _resolved_view(
                "abc",
                guild_name="NitroServer",
                channel_name="welcome",
                inviter_name="owner",
            )
        }
    )
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1
    # The `match` field uses regex match (m.group(0))
    assert events[0].match == "NitroServer\nwelcome\nowner"


async def test_pattern_miss_blocks():
    cfg = _cfg(rule_extras={"pattern": r"NotPresent"})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", guild_name="OtherServer")}
    )
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


# -- multi-invite ---------------------------------------------------------------


async def test_multi_invite_emits_event_per_match():
    cfg = _cfg(rule_extras={"min_members": 1})
    resolver = _FakeResolver(
        {
            "aaa": _resolved_view("aaa", approximate_member_count=10),
            "bbb": _resolved_view("bbb", approximate_member_count=20),
        }
    )
    msg = _msg(content="https://discord.gg/aaa and https://discord.gg/bbb")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert len(events) == 2
    assert {e.invite.code for e in events} == {"aaa", "bbb"}


async def test_multi_invite_only_matching_emit():
    cfg = _cfg(rule_extras={"max_members": 15})
    resolver = _FakeResolver(
        {
            "aaa": _resolved_view("aaa", approximate_member_count=10),
            "bbb": _resolved_view("bbb", approximate_member_count=50),
        }
    )
    msg = _msg(content="https://discord.gg/aaa and https://discord.gg/bbb")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert len(events) == 1
    assert events[0].invite.code == "aaa"


# -- match_unresolved -----------------------------------------------------------


async def test_unresolved_skipped_when_match_unresolved_false():
    cfg = _cfg(rule_extras={"min_members": 10, "match_unresolved": False})
    resolver = _FakeResolver({"abc": InviteView(code="abc", resolved=False)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_unresolved_with_match_unresolved_true_and_pattern_on_code():
    cfg = _cfg(
        rule_extras={
            "match_unresolved": True,
            "pattern": r"^abc.*",
        }
    )
    resolver = _FakeResolver({"abc123": InviteView(code="abc123", resolved=False)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc123"), resolver
        )
    ]
    assert len(events) == 1
    assert events[0].invite is not None
    assert events[0].invite.resolved is False
    assert events[0].invite.code == "abc123"


async def test_unresolved_with_match_unresolved_true_pattern_miss():
    cfg = _cfg(
        rule_extras={
            "match_unresolved": True,
            "pattern": r"^zzz",
        }
    )
    resolver = _FakeResolver({"abc123": InviteView(code="abc123", resolved=False)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc123"), resolver
        )
    ]
    assert events == []


async def test_unresolved_with_match_unresolved_true_skips_resolution_conditions():
    # min_members is set but invite is unresolved; with match_unresolved=True,
    # min_members is SKIPPED, so the rule should fire (pattern is satisfied).
    cfg = _cfg(
        rule_extras={
            "match_unresolved": True,
            "pattern": r".+",
            "min_members": 10,
        }
    )
    resolver = _FakeResolver({"abc": InviteView(code="abc", resolved=False)})
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert len(events) == 1


# -- common rule include/exclude ------------------------------------------------


async def test_common_rule_exclude_blocks_invite_rule():
    cfg = _cfg(rule_extras={"min_members": 1, "exclude": [2]})  # exclude channel_id=2
    resolver = _ExplodingResolver()
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


async def test_common_global_exclude_blocks_invite_rule():
    cfg = _cfg(
        rule_extras={"min_members": 1},
        globals_={"include": [], "exclude": [3], "default_rate_limit_seconds": 30},
    )
    resolver = _ExplodingResolver()
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://discord.gg/abc"), resolver
        )
    ]
    assert events == []


# -- early-out: no invite substring --------------------------------------------


async def test_no_invite_substring_skips_resolver():
    cfg = _cfg(rule_extras={"min_members": 1})
    resolver = _ExplodingResolver()
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="just some plain text with no links"), resolver
        )
    ]
    assert events == []


async def test_no_invite_substring_counted_resolver_zero_calls():
    cfg = _cfg(rule_extras={"min_members": 1})
    resolver = _FakeResolver()
    events = [
        e
        async for e in Matcher(cfg).evaluate(
            _msg(content="https://example.com/foo"), resolver
        )
    ]
    assert events == []
    assert resolver.calls == []


# -- mixed: message rule + invite rule ------------------------------------------


async def test_mixed_message_and_invite_rules_both_fire():
    cfg = _cfg(
        rule_extras={"min_members": 1},
        extra_rules=[
            {
                "name": "msg1",
                "type": "message",
                "pattern": r"hello",
                "message": "msg matched",
                "webhooks": ["alerts"],
            }
        ],
    )
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", approximate_member_count=5)}
    )
    msg = _msg(content="hello there https://discord.gg/abc")
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    names = [e.rule_name for e in events]
    assert "inv1" in names
    assert "msg1" in names
    # invite event has invite populated; message event doesn't
    msg_event = next(e for e in events if e.rule_name == "msg1")
    inv_event = next(e for e in events if e.rule_name == "inv1")
    assert msg_event.invite is None
    assert inv_event.invite is not None
    assert inv_event.invite.code == "abc"


# -- dedup of duplicate codes ---------------------------------------------------


async def test_duplicate_codes_resolver_called_once():
    cfg = _cfg(rule_extras={"min_members": 1})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", approximate_member_count=5)}
    )
    msg = _msg(
        content="https://discord.gg/abc and again https://discord.gg/abc"
    )
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert len(events) == 1
    assert resolver.calls == ["abc"]


# -- content fields on emitted event --------------------------------------------


async def test_invite_event_has_message_content():
    cfg = _cfg(rule_extras={"min_members": 1})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", approximate_member_count=5)}
    )
    content = "https://discord.gg/abc"
    msg = _msg(content=content)
    events = [e async for e in Matcher(cfg).evaluate(msg, resolver)]
    assert events[0].content == content
    assert events[0].author == "alice"
    assert events[0].channel_id == 2


# -- substring early-out variants -----------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "https://discord.gg/abc",
        "join https://discord.com/invite/abc",
        "old https://discordapp.com/invite/abc",
        "DISCORD.GG/abc",  # case-insensitive
    ],
)
async def test_invite_substring_variants_resolve(content):
    cfg = _cfg(rule_extras={"min_members": 1})
    resolver = _FakeResolver(
        {"abc": _resolved_view("abc", approximate_member_count=5)}
    )
    events = [e async for e in Matcher(cfg).evaluate(_msg(content=content), resolver)]
    assert len(events) == 1
