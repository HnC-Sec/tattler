import asyncio
import httpx
import respx
from tattler.bus import EventBus
from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.worker import NotifierWorker
from datetime import datetime, timezone


def _cfg() -> Config:
    return Config.model_validate({
        "webhooks": {"a": {"url": "https://example.com/a", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0}},
        "rules": [{"name": "r", "pattern": "x", "message": "m", "webhooks": ["a"]}],
    })


def _evt(content: str = "hi") -> MatchEvent:
    return MatchEvent(
        rule_name="r", rule_webhooks=("a",), rule_message_template="m",
        rule_rate_limit_seconds=0, author="x", author_id=1, channel_name="c",
        channel_id=2, guild_name="g", guild_id=3, content=content,
        message_id=4, message_link="https://x",
        timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
        is_edit=False, match="x", match_groups=(),
    )


@respx.mock
async def test_bus_drain_before_stop_processes_all_queued_events():
    route = respx.post("https://example.com/a").mock(return_value=httpx.Response(204))
    bus = EventBus()
    async with httpx.AsyncClient() as http:
        worker = NotifierWorker(bus, lambda: _cfg(), http)
        task = asyncio.create_task(worker.run())
        # publish multiple events
        for _ in range(5):
            await bus.publish(_evt())
        # drain first
        await asyncio.wait_for(bus.join(), timeout=2.0)
        # then stop
        worker.stop()
        await task
    assert route.call_count == 5
