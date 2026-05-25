import asyncio

import httpx
import pytest
import respx

from tattler.config.models import WebhookConfig
from tattler.notifier.webhooks.dispatcher import Dispatcher


@pytest.fixture
def webhook_cfg() -> WebhookConfig:
    return WebhookConfig(
        url="https://example.com/hook",
        format="generic",
        timeout_seconds=1.0,
        retries=2,
        backoff_base_seconds=0.0,  # zero backoff for fast tests
    )


@respx.mock
async def test_dispatch_success_2xx(webhook_cfg: WebhookConfig):
    route = respx.post("https://example.com/hook").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client)
        ok = await d.send(webhook_cfg, {"hello": "world"})
    assert ok is True
    assert route.called


@respx.mock
async def test_dispatch_retries_on_5xx_then_succeeds(webhook_cfg: WebhookConfig):
    route = respx.post("https://example.com/hook").mock(
        side_effect=[httpx.Response(500), httpx.Response(503), httpx.Response(200)]
    )
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client, sleep=lambda _s: asyncio.sleep(0))
        ok = await d.send(webhook_cfg, {"x": 1})
    assert ok is True
    assert route.call_count == 3


@respx.mock
async def test_dispatch_exhausts_retries_returns_false(webhook_cfg: WebhookConfig):
    route = respx.post("https://example.com/hook").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client, sleep=lambda _s: asyncio.sleep(0))
        ok = await d.send(webhook_cfg, {"x": 1})
    assert ok is False
    assert route.call_count == 3  # initial + 2 retries


@respx.mock
async def test_dispatch_does_not_retry_on_4xx_non_429(webhook_cfg: WebhookConfig):
    route = respx.post("https://example.com/hook").mock(return_value=httpx.Response(400))
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client, sleep=lambda _s: asyncio.sleep(0))
        ok = await d.send(webhook_cfg, {"x": 1})
    assert ok is False
    assert route.call_count == 1


@respx.mock
async def test_dispatch_retries_on_429(webhook_cfg: WebhookConfig):
    route = respx.post("https://example.com/hook").mock(
        side_effect=[httpx.Response(429), httpx.Response(200)]
    )
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client, sleep=lambda _s: asyncio.sleep(0))
        ok = await d.send(webhook_cfg, {"x": 1})
    assert ok is True
    assert route.call_count == 2


@respx.mock
async def test_dispatch_retries_on_timeout(webhook_cfg: WebhookConfig):
    respx.post("https://example.com/hook").mock(
        side_effect=[httpx.ConnectTimeout("boom"), httpx.Response(200)]
    )
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client, sleep=lambda _s: asyncio.sleep(0))
        ok = await d.send(webhook_cfg, {"x": 1})
    assert ok is True


@respx.mock
async def test_backoff_delays_increase_exponentially(webhook_cfg: WebhookConfig):
    respx.post("https://example.com/hook").mock(return_value=httpx.Response(500))
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    webhook_cfg = webhook_cfg.model_copy(update={"backoff_base_seconds": 1.0, "retries": 3})
    async with httpx.AsyncClient() as client:
        d = Dispatcher(client, sleep=fake_sleep)
        await d.send(webhook_cfg, {"x": 1})
    assert sleeps == [1.0, 2.0, 4.0]
