from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from tattler.config.models import Config, WebhookConfig

logger = logging.getLogger(__name__)


class _SendsWebhooks(Protocol):
    async def send(self, cfg: WebhookConfig, payload: dict[str, Any]) -> bool: ...


def build_status_summary(config: Config, server_names: Sequence[str]) -> dict[str, Any]:
    """Snapshot of what Tattler is watching: server count + names and rule count."""
    return {
        "servers": len(server_names),
        "rules": len(config.rules),
        "server_names": list(server_names),
    }


def _discord_payload(summary: dict[str, Any], author: str) -> dict[str, Any]:
    embed: dict[str, Any] = {
        "title": "Tattler online",
        "description": (
            f"Watching **{summary['servers']}** server(s) "
            f"with **{summary['rules']}** rule(s)."
        ),
        "fields": [
            {"name": "Servers", "value": str(summary["servers"]), "inline": True},
            {"name": "Rules", "value": str(summary["rules"]), "inline": True},
            {
                "name": "Watching",
                # Discord rejects empty field values and caps them at 1024 chars.
                "value": ("\n".join(summary["server_names"]) or "(none)")[:1024],
                "inline": False,
            },
        ],
    }
    if author:
        embed["author"] = {"name": author}
    return {"embeds": [embed]}


def _generic_payload(summary: dict[str, Any]) -> dict[str, Any]:
    return {"event": "startup", "status": summary}


class StatusReporter:
    """Sends a one-time startup status report to every configured webhook.

    Idempotent: only the first ``report()`` call dispatches, so the Discord
    ``on_ready`` event re-firing on reconnect does not re-announce.
    """

    def __init__(
        self,
        config_provider: Callable[[], Config],
        dispatcher: _SendsWebhooks,
    ) -> None:
        self._config_provider = config_provider
        self._dispatcher = dispatcher
        self._reported = False

    async def report(self, server_names: Sequence[str]) -> None:
        if self._reported:
            return
        self._reported = True

        cfg = self._config_provider()
        summary = build_status_summary(cfg, server_names)
        logger.info(
            "reporting startup status to %d webhook(s): %s",
            len(cfg.webhooks),
            summary,
        )
        for name, webhook_cfg in cfg.webhooks.items():
            if webhook_cfg.format == "discord":
                payload = _discord_payload(summary, cfg.globals.embed_author)
            else:
                payload = _generic_payload(summary)
            try:
                await self._dispatcher.send(webhook_cfg, payload)
            except Exception:
                logger.exception("failed to send startup status to webhook %r", name)
