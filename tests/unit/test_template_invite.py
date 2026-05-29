from datetime import datetime, timezone

from tattler.events import MatchEvent
from tattler.invites import InviteView
from tattler.notifier.template import render


def _event(**overrides) -> MatchEvent:
    defaults = dict(
        rule_name="r1",
        rule_webhooks=("alerts",),
        rule_rate_limit_seconds=30,
        author="alice",
        author_id=111,
        channel_name="general",
        channel_id=222,
        guild_name="my-server",
        guild_id=333,
        content="hello world",
        message_id=444,
        message_link="https://discord.com/channels/333/222/444",
        timestamp=datetime(2026, 5, 25, 14, 23, 0, tzinfo=timezone.utc),
        is_edit=False,
        match="hello",
        match_groups=("hel", "lo"),
    )
    defaults.update(overrides)
    return MatchEvent(**defaults)


_INVITE_TEMPLATE = (
    "{invite_code}|{invite_resolved}|"
    "{invite_guild_id}|{invite_guild_name}|"
    "{invite_channel_id}|{invite_channel_name}|"
    "{invite_inviter_id}|{invite_inviter_name}|"
    "{invite_member_count}|{invite_presence_count}|"
    "{invite_expires_at}|{invite_is_vanity}|"
    "{invite_verification_level}"
)


def test_renders_all_invite_placeholders_for_resolved_invite():
    invite = InviteView(
        code="abc123",
        resolved=True,
        guild_id=999,
        guild_name="Target Guild",
        guild_features=("COMMUNITY",),
        channel_id=888,
        channel_name="welcome",
        inviter_id=777,
        inviter_name="bob",
        approximate_member_count=42,
        approximate_presence_count=17,
        expires_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        is_vanity=True,
        verification_level="high",
    )
    event = _event(invite=invite)
    out = render(_INVITE_TEMPLATE, event)
    assert out == (
        "abc123|True|"
        "999|Target Guild|"
        "888|welcome|"
        "777|bob|"
        "42|17|"
        "2026-06-01T12:00:00+00:00|True|"
        "high"
    )


def test_all_invite_placeholders_empty_when_invite_is_none():
    event = _event(invite=None)
    out = render(_INVITE_TEMPLATE, event)
    assert out == "||" + "|" * 10  # 13 placeholders -> 12 separators, all empty
    # Equivalent: 13 empty fields joined by "|"
    assert out == "|".join([""] * 13)


def test_none_able_fields_render_empty_on_resolved_invite():
    invite = InviteView(
        code="xyz",
        resolved=True,
        guild_id=None,
        guild_name="",
        guild_features=(),
        channel_id=None,
        channel_name="",
        inviter_id=None,
        inviter_name="",
        approximate_member_count=None,
        approximate_presence_count=None,
        expires_at=None,
        is_vanity=False,
        verification_level="",
    )
    event = _event(invite=invite)
    out = render(_INVITE_TEMPLATE, event)
    assert out == (
        "xyz|True|"
        "||"
        "||"
        "||"
        "||"
        "|False|"
        ""
    )


def test_unresolved_invite_renders_code_and_resolved_false():
    invite = InviteView(code="deadcode", resolved=False)
    event = _event(invite=invite)
    out = render(_INVITE_TEMPLATE, event)
    # code populated, resolved=False, everything else default ("", None, False)
    assert out == (
        "deadcode|False|"
        "||"
        "||"
        "||"
        "||"
        "|False|"
        ""
    )


def test_message_rule_placeholders_still_work_with_invite_placeholders():
    invite = InviteView(code="abc", resolved=True, guild_name="g")
    event = _event(invite=invite)
    out = render("{rule_name}:{invite_code}", event)
    assert out == "r1:abc"


def test_unknown_placeholder_still_renders_empty_alongside_invite():
    invite = InviteView(code="abc", resolved=True)
    event = _event(invite=invite)
    out = render("{invite_code}|{nope}|{rule_name}", event)
    assert out == "abc||r1"
