from __future__ import annotations

from typing import Any

from tattler.config.models import EmbedConfig, GlobalConfig, RuleConfig
from tattler.events import MatchEvent
from tattler.notifier.template import render


class DiscordFormatter:
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        embed_cfg = rule.embed or EmbedConfig()
        embed: dict[str, Any] = {}

        # title — default: rule name (literal); override: rendered template
        title = render(embed_cfg.title, event) if embed_cfg.title is not None else rule.name
        if title != "":
            embed["title"] = title

        # description — default: rendered rule.message; override: rendered embed.description.
        # The `else` is unreachable: RuleConfig validates that message or embed.description is set.
        if embed_cfg.description is not None:
            description = render(embed_cfg.description, event)
        elif rule.message is not None:
            description = render(rule.message, event)
        else:
            description = ""
        if description != "":
            embed["description"] = description

        # url — default: event.message_link; override: rendered embed.url
        url = render(embed_cfg.url, event) if embed_cfg.url is not None else event.message_link
        if url != "":
            embed["url"] = url

        # author — default: globals.embed_author (literal); override: rendered embed.author
        author = render(embed_cfg.author, event) if embed_cfg.author is not None else globals_.embed_author
        if author != "":
            embed["author"] = {"name": author}

        # color — default: omitted; override: integer (already normalized by EmbedConfig)
        if embed_cfg.color is not None:
            embed["color"] = embed_cfg.color

        # footer — default: omitted; override: rendered embed.footer
        if embed_cfg.footer is not None:
            footer_text = render(embed_cfg.footer, event)
            if footer_text != "":
                embed["footer"] = {"text": footer_text}

        return {"embeds": [embed]}
