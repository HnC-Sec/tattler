from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.webhooks.generic import GenericFormatter


def _cfg() -> Config:
    return Config.model_validate({
        "webhooks": {
            "audit": {"url": "https://x", "format": "generic", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "hi", "message": "rendered: {content}", "webhooks": ["audit"]},
        ],
    })


def _event() -> MatchEvent:
    return MatchEvent(
        rule_name="r1",
        rule_webhooks=("audit",),
        rule_message_template="rendered: {content}",
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


def test_generic_payload_shape_renders_rule_message():
    cfg = _cfg()
    payload = GenericFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {
        "rule_name": "r1",
        "message": "rendered: hi",
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


def test_generic_payload_falls_back_to_embed_description_when_message_absent():
    cfg = Config.model_validate({
        "webhooks": {
            "audit": {"url": "https://x", "format": "generic", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "hi", "webhooks": ["audit"], "embed": {"description": "embed: {content}"}},
        ],
    })
    payload = GenericFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload["message"] == "embed: hi"
