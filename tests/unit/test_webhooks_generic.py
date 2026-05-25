from datetime import datetime, timezone

from tattler.events import MatchEvent
from tattler.notifier.webhooks.generic import GenericFormatter


def _event() -> MatchEvent:
    return MatchEvent(
        rule_name="r1",
        rule_webhooks=("alerts",),
        rule_message_template="t",
        rule_rate_limit_seconds=30,
        author="alice",
        author_id=111,
        channel_name="general",
        channel_id=222,
        guild_name="srv",
        guild_id=333,
        content="hi",
        message_id=444,
        message_link="https://discord.com/channels/333/222/444",
        timestamp=datetime(2026, 5, 25, 14, 23, 0, tzinfo=timezone.utc),
        is_edit=False,
        match="hi",
        match_groups=("hi",),
    )


def test_generic_payload_shape():
    payload = GenericFormatter().format(_event(), rendered_message="rendered")
    assert payload == {
        "rule_name": "r1",
        "message": "rendered",
        "event": {
            "author": "alice",
            "author_id": "111",
            "channel_name": "general",
            "channel_id": "222",
            "guild_name": "srv",
            "guild_id": "333",
            "content": "hi",
            "message_id": "444",
            "message_link": "https://discord.com/channels/333/222/444",
            "timestamp": "2026-05-25T14:23:00+00:00",
            "match": "hi",
            "match_groups": ["hi"],
            "is_edit": False,
        },
    }
