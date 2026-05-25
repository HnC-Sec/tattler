import re
import pytest
from pydantic import ValidationError

from tattler.config.models import Config, GlobalConfig, RuleConfig, WebhookConfig


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
