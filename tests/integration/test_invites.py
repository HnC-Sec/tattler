import asyncio
import json
from datetime import datetime, timezone

import httpx
import respx

from tattler.bus import EventBus
from tattler.config.models import Config
from tattler.invites import InviteView
from tattler.matcher import Matcher, MessageView
from tattler.notifier.worker import NotifierWorker


def _cfg() -> Config:
    return Config.model_validate({
        "globals": {
            "include": [],
            "exclude": [],
            "default_rate_limit_seconds": 60,
            "embed_author": "Tattler bot",
        },
        "webhooks": {
            "alerts": {
                "url": "https://example.com/alerts",
                "format": "discord",
                "timeout_seconds": 1,
                "retries": 0,
                "backoff_base_seconds": 0.0,
            },
        },
        "rules": [
            {
                "name": "scam_invite",
                "type": "invite",
                "max_members": 50,
                "webhooks": ["alerts"],
                "embed": {
                    "title": "Suspicious invite",
                    "description": "Code: {invite_code} | Target: {invite_guild_name} ({invite_member_count} members)",
                },
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


class _FakeResolver:
    def __init__(self, views: dict[str, InviteView]) -> None:
        self._views = views
        self.calls: list[str] = []

    async def resolve(self, code: str) -> InviteView:
        self.calls.append(code)
        return self._views.get(code, InviteView(code=code, resolved=False))


@respx.mock
async def test_invite_rule_end_to_end_emits_embed_with_invite_placeholders():
    route = respx.post("https://example.com/alerts").mock(
        return_value=httpx.Response(204)
    )
    cfg = _cfg()
    bus = EventBus()

    resolver = _FakeResolver({
        "abc123": InviteView(
            code="abc123",
            resolved=True,
            guild_id=999,
            guild_name="Tiny Server",
            channel_id=1,
            channel_name="lobby",
            inviter_id=42,
            inviter_name="someone",
            approximate_member_count=12,
            approximate_presence_count=3,
            verification_level="low",
        ),
    })

    async with httpx.AsyncClient() as http:
        worker = NotifierWorker(bus, lambda: cfg, http)
        task = asyncio.create_task(worker.run())

        async for event in Matcher(cfg).evaluate(
            _msg("look at this discord.gg/abc123"), resolver
        ):
            await bus.publish(event)

        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert route.call_count == 1
    body = json.loads(route.calls.last.request.read())
    assert body == {
        "embeds": [
            {
                "title": "Suspicious invite",
                "description": "Code: abc123 | Target: Tiny Server (12 members)",
                "url": "https://discord.com/x",
                "author": {"name": "Tattler bot"},
            }
        ]
    }
    assert resolver.calls == ["abc123"]
