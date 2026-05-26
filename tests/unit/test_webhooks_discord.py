from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.webhooks.discord import DiscordFormatter


def _cfg() -> Config:
    return Config.model_validate({
        "webhooks": {
            "alerts": {"url": "https://x", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "hi", "message": "rendered: {content}", "webhooks": ["alerts"]},
        ],
    })


def _event() -> MatchEvent:
    return MatchEvent(
        rule_name="r1",
        rule_webhooks=("alerts",),
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


def test_discord_payload_still_content_for_now():
    cfg = _cfg()
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {"content": "rendered: hi"}
