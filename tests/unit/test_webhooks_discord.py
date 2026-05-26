from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.webhooks.discord import DiscordFormatter


def _event(**overrides) -> MatchEvent:
    defaults = dict(
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
    defaults.update(overrides)
    return MatchEvent(**defaults)


def _cfg(rule_overrides=None, globals_overrides=None) -> Config:
    rule = {"name": "r1", "pattern": "hi", "message": "rendered: {content}", "webhooks": ["alerts"]}
    if rule_overrides:
        rule.update(rule_overrides)
    cfg_dict = {
        "webhooks": {
            "alerts": {"url": "https://x", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [rule],
    }
    if globals_overrides:
        cfg_dict["globals"] = globals_overrides
    return Config.model_validate(cfg_dict)


def test_default_embed_uses_rule_name_message_link_and_global_author():
    cfg = _cfg()
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {
        "embeds": [
            {
                "title": "r1",
                "description": "rendered: hi",
                "url": "https://discord.com/channels/333/222/444",
                "author": {"name": "Tattler bot"},
            }
        ]
    }


def test_global_embed_author_override_is_used():
    cfg = _cfg(globals_overrides={"embed_author": "MyBot"})
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload["embeds"][0]["author"] == {"name": "MyBot"}


def test_per_rule_overrides_replace_each_default_and_render_templates():
    cfg = _cfg(rule_overrides={
        "embed": {
            "title": "Alert: {rule_name}",
            "description": "{author} said {content}",
            "url": "https://example.com/{message_id}",
            "author": "{guild_name}",
            "color": "#ff5555",
            "footer": "in #{channel_name}",
        }
    })
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {
        "embeds": [
            {
                "title": "Alert: r1",
                "description": "alice said hi",
                "url": "https://example.com/444",
                "author": {"name": "srv"},
                "color": 0xFF5555,
                "footer": {"text": "in #general"},
            }
        ]
    }


def test_color_only_override_keeps_all_other_defaults():
    cfg = _cfg(rule_overrides={"embed": {"color": 0x00FF00}})
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    embed = payload["embeds"][0]
    assert embed["title"] == "r1"
    assert embed["description"] == "rendered: hi"
    assert embed["url"] == "https://discord.com/channels/333/222/444"
    assert embed["author"] == {"name": "Tattler bot"}
    assert embed["color"] == 0x00FF00


def test_empty_rendered_field_is_omitted_so_user_can_suppress_default():
    cfg = _cfg(rule_overrides={"embed": {"url": "", "author": ""}})
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    embed = payload["embeds"][0]
    assert "url" not in embed
    assert "author" not in embed
    assert embed["title"] == "r1"
    assert embed["description"] == "rendered: hi"


def test_description_falls_back_to_embed_description_when_message_absent():
    cfg_dict = {
        "webhooks": {
            "alerts": {"url": "https://x", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [{"name": "r1", "pattern": "hi", "webhooks": ["alerts"], "embed": {"description": "embed: {content}"}}],
    }
    cfg = Config.model_validate(cfg_dict)
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload["embeds"][0]["description"] == "embed: hi"


def test_footer_default_omitted_when_not_specified():
    cfg = _cfg()
    embed = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)["embeds"][0]
    assert "footer" not in embed
    assert "color" not in embed
