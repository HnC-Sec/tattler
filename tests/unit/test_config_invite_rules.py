import pytest
from pydantic import ValidationError

from tattler.config.models import Config, InviteRuleConfig, MessageRuleConfig


def _base():
    return {
        "globals": {"include": [], "exclude": [], "default_rate_limit_seconds": 30},
        "webhooks": {
            "alerts": {"url": "https://example.com/hook", "format": "generic"},
        },
        "rules": [],
    }


def _message_rule(**overrides):
    base = {
        "name": "msg",
        "pattern": r"\bfoo\b",
        "message": "{content}",
        "webhooks": ["alerts"],
    }
    base.update(overrides)
    return base


def _invite_rule(**overrides):
    base = {
        "name": "inv",
        "type": "invite",
        "target_guild_exclude": [123],
        "message": "{invite_code}",
        "webhooks": ["alerts"],
    }
    base.update(overrides)
    return base


# --- discrimination ----------------------------------------------------------


def test_rule_without_type_field_parses_as_message_rule():
    d = _base()
    d["rules"] = [_message_rule()]
    cfg = Config.model_validate(d)
    assert isinstance(cfg.rules[0], MessageRuleConfig)
    assert cfg.rules[0].type == "message"


def test_rule_with_type_message_parses_as_message_rule():
    d = _base()
    d["rules"] = [_message_rule(type="message")]
    cfg = Config.model_validate(d)
    assert isinstance(cfg.rules[0], MessageRuleConfig)


def test_rule_with_type_invite_parses_as_invite_rule():
    d = _base()
    d["rules"] = [_invite_rule()]
    cfg = Config.model_validate(d)
    assert isinstance(cfg.rules[0], InviteRuleConfig)
    assert cfg.rules[0].target_guild_exclude == [123]


def test_rejects_unknown_rule_type():
    d = _base()
    d["rules"] = [_message_rule(type="banana")]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


# --- invite rule defaults & shape -------------------------------------------


def test_invite_rule_pattern_is_optional():
    d = _base()
    d["rules"] = [_invite_rule(pattern=None)]
    cfg = Config.model_validate(d)
    assert cfg.rules[0].pattern is None


def test_invite_rule_pattern_when_set_is_validated_as_regex():
    d = _base()
    d["rules"] = [_invite_rule(pattern="(unclosed")]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_invite_rule_with_no_pattern_but_structured_conditions_is_valid():
    d = _base()
    d["rules"] = [_invite_rule(pattern=None, max_members=50)]
    cfg = Config.model_validate(d)
    assert cfg.rules[0].max_members == 50


def test_invite_rule_with_no_conditions_at_all_is_rejected():
    # No pattern, no target filter, no thresholds, no flags.
    d = _base()
    d["rules"] = [_invite_rule(pattern=None, target_guild_exclude=[])]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_invite_rule_rejects_min_greater_than_max():
    d = _base()
    d["rules"] = [_invite_rule(min_members=100, max_members=50)]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_invite_rule_rejects_unknown_verification_level():
    d = _base()
    d["rules"] = [_invite_rule(verification_level=["nope"])]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_invite_rule_accepts_all_verification_levels():
    d = _base()
    d["rules"] = [
        _invite_rule(verification_level=["none", "low", "medium", "high", "highest"])
    ]
    cfg = Config.model_validate(d)
    assert cfg.rules[0].verification_level == [
        "none",
        "low",
        "medium",
        "high",
        "highest",
    ]


# --- match_unresolved validation --------------------------------------------


def test_match_unresolved_true_with_only_resolution_dependent_conditions_rejected():
    # only condition is min_members (resolution-dependent) → rule could never
    # match an unresolved invite meaningfully.
    d = _base()
    d["rules"] = [
        _invite_rule(
            pattern=None,
            target_guild_exclude=[],
            min_members=10,
            match_unresolved=True,
        )
    ]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_match_unresolved_true_with_pattern_is_valid():
    d = _base()
    d["rules"] = [
        _invite_rule(
            pattern="(?i)scam",
            target_guild_exclude=[],
            match_unresolved=True,
        )
    ]
    cfg = Config.model_validate(d)
    assert cfg.rules[0].match_unresolved is True


# --- message/embed.description still required for invite rules --------------


def test_invite_rule_requires_message_or_embed_description():
    d = _base()
    bad = _invite_rule()
    bad.pop("message")
    d["rules"] = [bad]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_invite_rule_with_embed_description_only_is_valid():
    d = _base()
    rule = _invite_rule()
    rule.pop("message")
    rule["embed"] = {"description": "{invite_code}"}
    d["rules"] = [rule]
    cfg = Config.model_validate(d)
    assert cfg.rules[0].message is None


# --- extra fields forbidden -------------------------------------------------


def test_invite_rule_rejects_unknown_field():
    d = _base()
    d["rules"] = [_invite_rule(unknown_field=True)]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


# --- duplicate names across types -------------------------------------------


def test_duplicate_names_across_rule_types_rejected():
    d = _base()
    d["rules"] = [_message_rule(name="dup"), _invite_rule(name="dup")]
    with pytest.raises(ValidationError):
        Config.model_validate(d)


# --- globals: invite cache knobs --------------------------------------------


def test_globals_invite_cache_defaults():
    d = _base()
    d["rules"] = [_message_rule()]
    cfg = Config.model_validate(d)
    assert cfg.globals.invite_cache_ttl_seconds == 600
    assert cfg.globals.invite_cache_max_entries == 1024


def test_globals_invite_cache_overrides():
    d = _base()
    d["globals"]["invite_cache_ttl_seconds"] = 120
    d["globals"]["invite_cache_max_entries"] = 64
    d["rules"] = [_message_rule()]
    cfg = Config.model_validate(d)
    assert cfg.globals.invite_cache_ttl_seconds == 120
    assert cfg.globals.invite_cache_max_entries == 64
