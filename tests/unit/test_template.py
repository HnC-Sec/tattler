from datetime import datetime, timezone

from tattler.events import MatchEvent
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


def test_renders_all_placeholders():
    event = _event()
    out = render(
        "{rule_name}|{author}|{author_id}|{channel_name}|{channel_id}|"
        "{guild_name}|{guild_id}|{content}|{message_id}|{message_link}|"
        "{timestamp}|{match}|{match_groups}|{is_edit}",
        event,
    )
    assert out == (
        "r1|alice|111|general|222|"
        "my-server|333|hello world|444|https://discord.com/channels/333/222/444|"
        "2026-05-25T14:23:00+00:00|hello|hel,lo|False"
    )


def test_unknown_placeholder_renders_empty():
    out = render("a {nope} b", _event())
    assert out == "a  b"


def test_literal_braces_via_doubling():
    out = render("a {{x}} b {rule_name}", _event())
    assert out == "a {x} b r1"


def test_dm_with_no_guild():
    event = _event(guild_id=None, guild_name="")
    out = render("{guild_id}|{guild_name}", event)
    assert out == "|"
