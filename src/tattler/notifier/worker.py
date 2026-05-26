from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import httpx

from tattler.bus import EventBus
from tattler.config.models import Config
from tattler.notifier.rate_limit import RateLimiter
from tattler.notifier.webhooks.base import WebhookFormatter
from tattler.notifier.webhooks.dispatcher import Dispatcher
from tattler.notifier.webhooks.discord import DiscordFormatter
from tattler.notifier.webhooks.generic import GenericFormatter

logger = logging.getLogger(__name__)

_FORMATTERS: dict[str, WebhookFormatter] = {
    "generic": GenericFormatter(),
    "discord": DiscordFormatter(),
}


class NotifierWorker:
    def __init__(
        self,
        bus: EventBus,
        config_provider: Callable[[], Config],
        http_client: httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._config_provider = config_provider
        self._dispatcher = Dispatcher(http_client)
        self._rate_limiter = RateLimiter(clock=clock)
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        while not self._stopped:
            try:
                event = await asyncio.wait_for(self._bus.get(), timeout=0.1)
            except TimeoutError:
                continue
            try:
                await self._handle(event)
            except Exception:
                logger.exception("notifier worker: unhandled error processing event")
            finally:
                self._bus.task_done()

    async def _handle(self, event) -> None:
        cfg = self._config_provider()
        cooldown = event.rule_rate_limit_seconds
        if not self._rate_limiter.allow(event.rule_name, event.channel_id, cooldown):
            logger.debug("rate-limited: rule=%s channel=%s", event.rule_name, event.channel_id)
            return

        rule = next((r for r in cfg.rules if r.name == event.rule_name), None)
        if rule is None:
            logger.warning(
                "event for rule %r dropped: rule no longer in config",
                event.rule_name,
            )
            return

        for name in event.rule_webhooks:
            webhook_cfg = cfg.webhooks.get(name)
            if webhook_cfg is None:
                logger.warning("event %s references unknown webhook %r", event.rule_name, name)
                continue
            formatter = _FORMATTERS[webhook_cfg.format]
            payload = formatter.format(event, rule, cfg.globals)
            await self._dispatcher.send(webhook_cfg, payload)
