from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timezone

import discord  # provided by discord.py-self

from tattler.bus import EventBus
from tattler.config.models import Config
from tattler.health import HealthFiles
from tattler.matcher import Matcher, MessageView

logger = logging.getLogger(__name__)


def _extract_view(msg: "discord.Message", is_edit: bool) -> MessageView:
    embed_parts: list[str] = []
    for e in msg.embeds or []:
        if e.title:
            embed_parts.append(e.title)
        if e.description:
            embed_parts.append(e.description)
        for f in e.fields or []:
            if f.name:
                embed_parts.append(f.name)
            if f.value:
                embed_parts.append(f.value)
    attachment_names = tuple(a.filename for a in (msg.attachments or []))
    role_ids: tuple[int, ...] = ()
    member = getattr(msg, "author", None)
    if member is not None:
        roles = getattr(member, "roles", None) or ()
        role_ids = tuple(r.id for r in roles if hasattr(r, "id"))
    guild = msg.guild
    return MessageView(
        author=str(msg.author),
        author_id=int(msg.author.id),
        channel_name=getattr(msg.channel, "name", "DM"),
        channel_id=int(msg.channel.id),
        guild_name=guild.name if guild else "",
        guild_id=int(guild.id) if guild else None,
        author_role_ids=role_ids,
        content=msg.content or "",
        embed_text="\n".join(embed_parts),
        attachment_filenames=attachment_names,
        message_id=int(msg.id),
        message_link=msg.jump_url,
        timestamp=(msg.edited_at or msg.created_at).astimezone(timezone.utc),
        is_edit=is_edit,
    )


class TattlerClient(discord.Client):
    def __init__(
        self,
        config_provider: Callable[[], Config],
        bus: EventBus,
        health: HealthFiles,
    ) -> None:
        super().__init__()
        self._config_provider = config_provider
        self._bus = bus
        self._health = health

    async def on_ready(self) -> None:
        logger.info("discord client connected as %s", self.user)
        self._health.mark_ready()

    async def on_disconnect(self) -> None:
        logger.warning("discord client disconnected")
        self._health.mark_unready()

    async def on_message(self, message: "discord.Message") -> None:
        await self._handle(message, is_edit=False)

    async def on_message_edit(self, _before: "discord.Message", after: "discord.Message") -> None:
        await self._handle(after, is_edit=True)

    async def _handle(self, message: "discord.Message", is_edit: bool) -> None:
        try:
            view = _extract_view(message, is_edit=is_edit)
        except Exception:
            logger.exception("failed to project discord message")
            return
        matcher = Matcher(self._config_provider())
        for event in matcher.evaluate(view):
            await self._bus.publish(event)
