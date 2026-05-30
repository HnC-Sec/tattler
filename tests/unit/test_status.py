from tattler.config.models import Config
from tattler.notifier.status import (
    StatusReporter,
    build_status_summary,
)


def _cfg(*, webhooks=None, rules=None, globals_=None) -> Config:
    cfg_dict = {
        "webhooks": webhooks
        or {
            "alerts": {"url": "https://x", "format": "discord", "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": rules
        if rules is not None
        else [
            {"name": "r1", "pattern": "hi", "message": "m", "webhooks": ["alerts"]},
        ],
    }
    if globals_:
        cfg_dict["globals"] = globals_
    return Config.model_validate(cfg_dict)


class FakeDispatcher:
    """Records (cfg, payload) for every send call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def send(self, cfg, payload) -> bool:
        self.calls.append((cfg, payload))
        return True


def test_summary_counts_servers_rules_and_lists_server_names():
    cfg = _cfg(
        rules=[
            {"name": "r1", "pattern": "a", "message": "m", "webhooks": ["alerts"]},
            {"name": "r2", "type": "invite", "pattern": "b", "message": "m", "webhooks": ["alerts"]},
        ]
    )
    summary = build_status_summary(cfg, server_names=["Guild A", "Guild B", "Guild C"])
    assert summary == {
        "servers": 3,
        "rules": 2,
        "server_names": ["Guild A", "Guild B", "Guild C"],
    }


def test_summary_handles_no_servers():
    summary = build_status_summary(_cfg(), server_names=[])
    assert summary["servers"] == 0
    assert summary["server_names"] == []


async def test_reporter_sends_to_every_configured_webhook():
    cfg = _cfg(
        webhooks={
            "a": {"url": "https://a", "format": "discord", "retries": 0, "backoff_base_seconds": 0.0},
            "b": {"url": "https://b", "format": "generic", "retries": 0, "backoff_base_seconds": 0.0},
        },
        rules=[{"name": "r1", "pattern": "x", "message": "m", "webhooks": ["a", "b"]}],
    )
    dispatcher = FakeDispatcher()
    reporter = StatusReporter(lambda: cfg, dispatcher)

    await reporter.report(server_names=["S1"])

    sent_urls = {call[0].url for call in dispatcher.calls}
    assert sent_urls == {"https://a", "https://b"}


async def test_reporter_uses_discord_embed_for_discord_format():
    cfg = _cfg(globals_={"embed_author": "MyBot"})
    dispatcher = FakeDispatcher()
    reporter = StatusReporter(lambda: cfg, dispatcher)

    await reporter.report(server_names=["Guild A"])

    _cfg_sent, payload = dispatcher.calls[0]
    assert "embeds" in payload
    embed = payload["embeds"][0]
    assert embed["author"] == {"name": "MyBot"}
    # server count, rule count and the server name all surface somewhere in the embed text.
    blob = embed["description"] + "".join(
        f["name"] + f["value"] for f in embed["fields"]
    )
    assert "1" in blob
    assert "Guild A" in blob


async def test_reporter_uses_generic_payload_for_generic_format():
    cfg = _cfg(
        webhooks={"b": {"url": "https://b", "format": "generic", "retries": 0, "backoff_base_seconds": 0.0}},
        rules=[{"name": "r1", "pattern": "x", "message": "m", "webhooks": ["b"]}],
    )
    dispatcher = FakeDispatcher()
    reporter = StatusReporter(lambda: cfg, dispatcher)

    await reporter.report(server_names=["Guild A", "Guild B"])

    _cfg_sent, payload = dispatcher.calls[0]
    assert payload["event"] == "startup"
    assert payload["status"] == {
        "servers": 2,
        "rules": 1,
        "server_names": ["Guild A", "Guild B"],
    }


async def test_reporter_is_idempotent_only_reports_once():
    cfg = _cfg()
    dispatcher = FakeDispatcher()
    reporter = StatusReporter(lambda: cfg, dispatcher)

    await reporter.report(server_names=["S1"])
    await reporter.report(server_names=["S1"])

    assert len(dispatcher.calls) == 1


async def test_reporter_continues_when_one_webhook_send_raises():
    cfg = _cfg(
        webhooks={
            "a": {"url": "https://a", "format": "discord", "retries": 0, "backoff_base_seconds": 0.0},
            "b": {"url": "https://b", "format": "generic", "retries": 0, "backoff_base_seconds": 0.0},
        },
        rules=[{"name": "r1", "pattern": "x", "message": "m", "webhooks": ["a", "b"]}],
    )

    class FlakyDispatcher(FakeDispatcher):
        async def send(self, cfg, payload) -> bool:
            self.calls.append((cfg, payload))
            if cfg.url == "https://a":
                raise RuntimeError("boom")
            return True

    dispatcher = FlakyDispatcher()
    reporter = StatusReporter(lambda: cfg, dispatcher)

    await reporter.report(server_names=["S1"])

    # both webhooks attempted despite the first raising
    assert {call[0].url for call in dispatcher.calls} == {"https://a", "https://b"}
