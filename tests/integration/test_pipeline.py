import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from tattler.bus import EventBus
from tattler.config.models import Config
from tattler.matcher import Matcher, MessageView
from tattler.notifier.worker import NotifierWorker


def _cfg() -> Config:
    return Config.model_validate({
        "globals": {"include": [], "exclude": [], "default_rate_limit_seconds": 60},
        "webhooks": {
            "alerts": {"url": "https://example.com/alerts", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {
                "name": "say_hi",
                "pattern": r"(?i)\bhello\b",
                "message": "{author} said hello in #{channel_name}",
                "webhooks": ["alerts"],
                "rate_limit_seconds": 60,
            }
        ],
    })


def _msg(content: str) -> MessageView:
    return MessageView(
        author="alice",
        author_id=10,
        channel_name="general",
        channel_id=20,
        guild_name="srv",
        guild_id=30,
        author_role_ids=(),
        content=content,
        embed_text="",
        attachment_filenames=(),
        message_id=100,
        message_link="https://discord.com/x",
        timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
        is_edit=False,
    )


@respx.mock
async def test_happy_path_pipeline():
    route = respx.post("https://example.com/alerts").mock(return_value=httpx.Response(204))
    cfg = _cfg()
    bus = EventBus()

    async with httpx.AsyncClient() as http:
        worker = NotifierWorker(bus, lambda: cfg, http)
        task = asyncio.create_task(worker.run())

        for event in Matcher(cfg).evaluate(_msg("oh hello there")):
            await bus.publish(event)

        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert route.call_count == 1
    body = json.loads(route.calls.last.request.read())
    assert body == {
        "embeds": [
            {
                "title": "say_hi",
                "description": "alice said hello in #general",
                "url": "https://discord.com/x",
                "author": {"name": "Tattler bot"},
            }
        ]
    }


@respx.mock
async def test_rate_limit_suppresses_second_event():
    respx.post("https://example.com/alerts").mock(return_value=httpx.Response(204))
    cfg = _cfg()
    bus = EventBus()

    async with httpx.AsyncClient() as http:
        worker = NotifierWorker(bus, lambda: cfg, http, clock=lambda: 100.0)
        task = asyncio.create_task(worker.run())

        for content in ("hello a", "hello b"):
            for event in Matcher(cfg).evaluate(_msg(content)):
                await bus.publish(event)

        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert len(respx.calls) == 1
