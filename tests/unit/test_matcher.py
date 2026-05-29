from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.invites import InviteView
from tattler.matcher import Matcher, MessageView


class _NoopResolver:
    """Resolver that raises if accidentally called — message-rule tests
    should never trigger invite resolution."""

    async def resolve(self, code: str) -> InviteView:
        raise NotImplementedError("resolver should not be called for message-rule tests")


_resolver = _NoopResolver()


def _cfg(**overrides) -> Config:
    base = {
        "globals": {"include": [], "exclude": [], "default_rate_limit_seconds": 30},
        "webhooks": {"alerts": {"url": "https://x", "format": "generic"}},
        "rules": [
            {
                "name": "r1",
                "pattern": r"\bfoo\b",
                "include": [],
                "exclude": [],
                "message": "{content}",
                "webhooks": ["alerts"],
            }
        ],
    }
    base.update(overrides)
    return Config.model_validate(base)


def _msg(**overrides) -> MessageView:
    defaults = dict(
        author="alice",
        author_id=1,
        channel_name="general",
        channel_id=2,
        guild_name="srv",
        guild_id=3,
        author_role_ids=(),
        content="hello foo world",
        embed_text="",
        attachment_filenames=(),
        message_id=4,
        message_link="https://discord.com/x",
        timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
        is_edit=False,
    )
    defaults.update(overrides)
    return MessageView(**defaults)


async def test_match_on_content():
    events = [e async for e in Matcher(_cfg()).evaluate(_msg(), _resolver)]
    assert len(events) == 1
    assert events[0].rule_name == "r1"
    assert events[0].match == "foo"


async def test_no_match():
    events = [
        e
        async for e in Matcher(_cfg()).evaluate(_msg(content="nothing here"), _resolver)
    ]
    assert events == []


async def test_match_in_embed_text():
    events = [
        e
        async for e in Matcher(_cfg()).evaluate(
            _msg(content="hi", embed_text="foo in embed"), _resolver
        )
    ]
    assert len(events) == 1


async def test_match_in_attachment_filename():
    events = [
        e
        async for e in Matcher(_cfg()).evaluate(
            _msg(content="hi", attachment_filenames=("foo.png",)), _resolver
        )
    ]
    assert len(events) == 1


async def test_global_exclude_blocks_rule():
    cfg = _cfg(globals={"include": [], "exclude": [2], "default_rate_limit_seconds": 30})
    events = [e async for e in Matcher(cfg).evaluate(_msg(), _resolver)]
    assert events == []


async def test_rule_exclude_blocks_rule():
    cfg = _cfg()
    cfg.rules[0].exclude.append(1)  # author_id
    events = [e async for e in Matcher(cfg).evaluate(_msg(), _resolver)]
    assert events == []


async def test_include_empty_means_allow_all():
    events = [e async for e in Matcher(_cfg()).evaluate(_msg(), _resolver)]
    assert len(events) == 1


async def test_global_include_requires_membership():
    cfg = _cfg(globals={"include": [999], "exclude": [], "default_rate_limit_seconds": 30})
    events = [e async for e in Matcher(cfg).evaluate(_msg(), _resolver)]
    assert events == []  # message has no snowflake in {999}


async def test_global_include_passes_when_role_matches():
    cfg = _cfg(globals={"include": [777], "exclude": [], "default_rate_limit_seconds": 30})
    events = [
        e async for e in Matcher(cfg).evaluate(_msg(author_role_ids=(777,)), _resolver)
    ]
    assert len(events) == 1


async def test_rule_rate_limit_falls_back_to_global_default_in_event():
    cfg = _cfg()
    cfg.rules[0].rate_limit_seconds = None
    events = [e async for e in Matcher(cfg).evaluate(_msg(), _resolver)]
    assert events[0].rule_rate_limit_seconds == 30


async def test_exclude_wins_over_include():
    cfg = _cfg(globals={"include": [1], "exclude": [1], "default_rate_limit_seconds": 30})
    events = [e async for e in Matcher(cfg).evaluate(_msg(), _resolver)]
    assert events == []


async def test_match_groups_captured():
    cfg = _cfg()
    cfg.rules[0] = cfg.rules[0].model_copy(update={"pattern": r"(\w+)\s(\w+)"})
    # force recompile via re-validation
    cfg = Config.model_validate(cfg.model_dump())
    events = [
        e async for e in Matcher(cfg).evaluate(_msg(content="alpha beta"), _resolver)
    ]
    assert events[0].match_groups == ("alpha", "beta")


async def test_edit_event_flag_propagates():
    events = [e async for e in Matcher(_cfg()).evaluate(_msg(is_edit=True), _resolver)]
    assert events[0].is_edit is True
