from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from tattler.config.models import WebhookConfig

logger = logging.getLogger(__name__)


class Dispatcher:
    """POSTs payloads to a webhook with bounded exponential-backoff retry."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep

    async def send(self, cfg: WebhookConfig, payload: dict[str, Any]) -> bool:
        attempts = cfg.retries + 1
        for attempt in range(attempts):
            outcome = await self._try_once(cfg, payload)
            if outcome == "success":
                return True
            if outcome == "permanent":
                return False
            # transient: retry if attempts remain
            if attempt < attempts - 1:
                delay = cfg.backoff_base_seconds * (2 ** attempt)
                await self._sleep(delay)
        logger.warning("webhook %s: exhausted retries", cfg.url)
        return False

    async def _try_once(self, cfg: WebhookConfig, payload: dict[str, Any]) -> str:
        try:
            resp = await self._client.post(cfg.url, json=payload, timeout=cfg.timeout_seconds)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.info("webhook %s: transient transport error: %s", cfg.url, exc)
            return "transient"
        if 200 <= resp.status_code < 300:
            logger.info("webhook %s: %s", cfg.url, resp.status_code)
            return "success"
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            logger.info("webhook %s: transient status %s", cfg.url, resp.status_code)
            return "transient"
        logger.warning("webhook %s: permanent status %s", cfg.url, resp.status_code)
        return "permanent"
