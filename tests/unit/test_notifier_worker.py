import asyncio
from datetime import datetime, timezone

import httpx
import pytest
import respx

from tattler.bus import EventBus
from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.worker import NotifierWorker


def _cfg() -> Config:
    return Config.model_validate({
        "webhooks": {
            "alerts": {"url": "https://example.com/alerts", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
            "audit": {"url": "https://example.com/audit", "format": "generic", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "foo", "message": "hit: {content}", "webhooks": ["alerts", "audit"]},
        ],
    })


def _event(**overrides) -> MatchEvent:
    defaults = dict(
        rule_name="r1",
        rule_webhooks=("alerts", "audit"),
        rule_message_template="hit: {content}",
        rule_rate_limit_seconds=0,
        author="alice",
        author_id=1,
        channel_name="g",
        channel_id=2,
        guild_name="s",
        guild_id=3,
        content="foo bar",
        message_id=4,
        message_link="https://x",
        timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
        is_edit=False,
        match="foo",
        match_groups=(),
    )
    defaults.update(overrides)
    return MatchEvent(**defaults)


@respx.mock
async def test_worker_dispatches_to_all_named_webhooks_for_event():
    alerts = respx.post("https://example.com/alerts").mock(return_value=httpx.Response(204))
    audit = respx.post("https://example.com/audit").mock(return_value=httpx.Response(204))

    bus = EventBus()
    cfg_holder = lambda: _cfg()
    async with httpx.AsyncClient() as client:
        worker = NotifierWorker(bus, cfg_holder, client)
        task = asyncio.create_task(worker.run())
        await bus.publish(_event())
        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert alerts.called
    assert audit.called
    assert alerts.calls.last.request.read() == b'{"content":"hit: foo bar"}'


@respx.mock
async def test_worker_respects_rate_limit():
    respx.post("https://example.com/alerts").mock(return_value=httpx.Response(204))
    respx.post("https://example.com/audit").mock(return_value=httpx.Response(204))

    bus = EventBus()
    cfg_holder = lambda: _cfg()
    async with httpx.AsyncClient() as client:
        worker = NotifierWorker(bus, cfg_holder, client, clock=lambda: 100.0)
        task = asyncio.create_task(worker.run())
        # rate limit of 30 in the rule (rule_rate_limit_seconds=0 in event is overridden by config lookup)
        await bus.publish(_event(rule_rate_limit_seconds=60))
        await bus.publish(_event(rule_rate_limit_seconds=60))
        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    # First event fires both webhooks; second is rate-limited and fires none.
    assert len(respx.calls) == 2


@respx.mock
async def test_worker_skips_event_for_unknown_webhook_name():
    bus = EventBus()
    cfg_holder = lambda: _cfg()
    async with httpx.AsyncClient() as client:
        worker = NotifierWorker(bus, cfg_holder, client)
        task = asyncio.create_task(worker.run())
        await bus.publish(_event(rule_webhooks=("nope",)))
        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert len(respx.calls) == 0


@respx.mock
async def test_worker_drops_event_for_unknown_rule_name(caplog):
    respx.post("https://example.com/alerts").mock(return_value=httpx.Response(204))
    respx.post("https://example.com/audit").mock(return_value=httpx.Response(204))

    bus = EventBus()
    cfg_holder = lambda: _cfg()
    async with httpx.AsyncClient() as client:
        worker = NotifierWorker(bus, cfg_holder, client)
        task = asyncio.create_task(worker.run())
        await bus.publish(_event(rule_name="vanished"))
        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert len(respx.calls) == 0
