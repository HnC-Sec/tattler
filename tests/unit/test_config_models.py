import re
import pytest
from pydantic import ValidationError

from tattler.config.models import Config, EmbedConfig, GlobalConfig, RuleConfig, WebhookConfig


def _minimal_dict():
    return {
        "globals": {"include": [], "exclude": [], "default_rate_limit_seconds": 30},
        "webhooks": {
            "alerts": {
                "url": "https://example.com/hook",
                "format": "generic",
                "timeout_seconds": 5,
                "retries": 3,
                "backoff_base_seconds": 1.0,
            }
        },
        "rules": [
            {
                "name": "r1",
                "pattern": r"\bfoo\b",
                "include": [],
                "exclude": [],
                "rate_limit_seconds": 60,
                "message": "matched {rule_name}",
                "webhooks": ["alerts"],
            }
        ],
    }


def test_loads_minimal_valid_config():
    cfg = Config.model_validate(_minimal_dict())
    assert cfg.rules[0].name == "r1"
    assert cfg.webhooks["alerts"].format == "generic"


def test_rule_pattern_compiled():
    cfg = Config.model_validate(_minimal_dict())
    assert isinstance(cfg.rules[0].compiled_pattern, re.Pattern)
    assert cfg.rules[0].compiled_pattern.search("hello foo bar")


def test_rejects_invalid_regex():
    d = _minimal_dict()
    d["rules"][0]["pattern"] = "(unclosed"
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rejects_unknown_webhook_reference():
    d = _minimal_dict()
    d["rules"][0]["webhooks"] = ["does_not_exist"]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rejects_empty_webhooks_list():
    d = _minimal_dict()
    d["rules"][0]["webhooks"] = []
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rejects_invalid_webhook_format():
    d = _minimal_dict()
    d["webhooks"]["alerts"]["format"] = "slack"
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rejects_duplicate_rule_names():
    d = _minimal_dict()
    d["rules"].append(dict(d["rules"][0]))
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rule_rate_limit_falls_back_to_global_default():
    d = _minimal_dict()
    d["rules"][0].pop("rate_limit_seconds")
    cfg = Config.model_validate(d)
    assert cfg.rules[0].effective_rate_limit(cfg.globals) == 30


def test_globals_defaults_when_section_omitted():
    d = _minimal_dict()
    d.pop("globals")
    cfg = Config.model_validate(d)
    assert cfg.globals.include == []
    assert cfg.globals.exclude == []
    assert cfg.globals.default_rate_limit_seconds == 30
    assert cfg.globals.embed_author == "Tattler bot"


def test_embed_config_parses_all_fields_and_normalizes_color_hex_string():
    embed = EmbedConfig.model_validate({
        "title": "{rule_name}",
        "description": "{content}",
        "url": "{message_link}",
        "author": "Bot",
        "color": "#ff5555",
        "footer": "from {guild_name}",
    })
    assert embed.title == "{rule_name}"
    assert embed.description == "{content}"
    assert embed.url == "{message_link}"
    assert embed.author == "Bot"
    assert embed.color == 0xFF5555
    assert embed.footer == "from {guild_name}"


def test_embed_config_color_accepts_0x_prefix_and_uppercase():
    assert EmbedConfig.model_validate({"color": "0xFF5555"}).color == 0xFF5555
    assert EmbedConfig.model_validate({"color": "#FF5555"}).color == 0xFF5555


def test_embed_config_color_accepts_integer():
    assert EmbedConfig.model_validate({"color": 16734293}).color == 16734293


def test_embed_config_rejects_malformed_color():
    for bad in ["red", "#zzzzzz", "#fffffff", "#fff", -1, 0x1000000]:
        with pytest.raises(ValidationError):
            EmbedConfig.model_validate({"color": bad})


def test_embed_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        EmbedConfig.model_validate({"thumbnail": "https://example.com/x.png"})


def test_globals_embed_author_defaults_to_tattler_bot():
    g = GlobalConfig()
    assert g.embed_author == "Tattler bot"


def test_globals_embed_author_can_be_overridden():
    g = GlobalConfig.model_validate({"embed_author": "MyBot"})
    assert g.embed_author == "MyBot"


def test_rule_message_optional_when_embed_description_set():
    d = _minimal_dict()
    d["rules"][0].pop("message")
    d["rules"][0]["embed"] = {"description": "{content}"}
    cfg = Config.model_validate(d)
    assert cfg.rules[0].message is None
    assert cfg.rules[0].embed.description == "{content}"


def test_rule_rejects_when_both_message_and_embed_description_missing():
    d = _minimal_dict()
    d["rules"][0].pop("message")
    d["rules"][0]["embed"] = {"title": "t"}
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rule_rejects_when_message_and_embed_both_missing():
    d = _minimal_dict()
    d["rules"][0].pop("message")
    with pytest.raises(ValidationError):
        Config.model_validate(d)
