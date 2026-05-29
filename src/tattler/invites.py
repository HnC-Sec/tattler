from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import discord


logger = logging.getLogger(__name__)


_INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/([a-zA-Z0-9-]+)",
    re.IGNORECASE,
)


_VERIFICATION_LEVELS = frozenset({"none", "low", "medium", "high", "highest"})


def extract_invite_codes(text: str) -> list[str]:
    """Return de-duplicated Discord invite codes in first-seen order."""
    seen: dict[str, None] = {}
    for m in _INVITE_RE.finditer(text):
        code = m.group(1)
        if code not in seen:
            seen[code] = None
    return list(seen)


@dataclass(frozen=True)
class InviteView:
    """Library-agnostic projection of a resolved Discord invite."""

    code: str
    resolved: bool
    guild_id: int | None = None
    guild_name: str = ""
    guild_features: tuple[str, ...] = ()
    channel_id: int | None = None
    channel_name: str = ""
    inviter_id: int | None = None
    inviter_name: str = ""
    approximate_member_count: int | None = None
    approximate_presence_count: int | None = None
    expires_at: datetime | None = None
    is_vanity: bool = False
    verification_level: str = ""


def _map_verification_level(level: object) -> str:
    """Map a discord.VerificationLevel-like enum to a lowercase string.

    Returns "" for unknown values or missing levels.
    """
    if level is None:
        return ""
    name = getattr(level, "name", None)
    if not isinstance(name, str):
        return ""
    name = name.lower()
    if name in _VERIFICATION_LEVELS:
        return name
    return ""


def _build_view(code: str, invite: object) -> InviteView:
    """Project a discord.Invite-like object into an InviteView."""
    guild = getattr(invite, "guild", None)
    channel = getattr(invite, "channel", None)
    inviter = getattr(invite, "inviter", None)

    guild_id: int | None = None
    guild_name = ""
    guild_features: tuple[str, ...] = ()
    verification_level = ""
    vanity_url_code: str | None = None
    if guild is not None:
        guild_id = getattr(guild, "id", None)
        guild_name = getattr(guild, "name", "") or ""
        features = getattr(guild, "features", None)
        if features:
            guild_features = tuple(str(f) for f in features)
        verification_level = _map_verification_level(
            getattr(guild, "verification_level", None)
        )
        vanity_url_code = getattr(guild, "vanity_url_code", None)

    channel_id: int | None = None
    channel_name = ""
    if channel is not None:
        channel_id = getattr(channel, "id", None)
        channel_name = getattr(channel, "name", "") or ""

    inviter_id: int | None = None
    inviter_name = ""
    if inviter is not None:
        inviter_id = getattr(inviter, "id", None)
        inviter_name = getattr(inviter, "name", "") or ""

    is_vanity = bool(
        vanity_url_code is not None
        and isinstance(vanity_url_code, str)
        and vanity_url_code.lower() == code.lower()
    )

    return InviteView(
        code=code,
        resolved=True,
        guild_id=guild_id,
        guild_name=guild_name,
        guild_features=guild_features,
        channel_id=channel_id,
        channel_name=channel_name,
        inviter_id=inviter_id,
        inviter_name=inviter_name,
        approximate_member_count=getattr(invite, "approximate_member_count", None),
        approximate_presence_count=getattr(invite, "approximate_presence_count", None),
        expires_at=getattr(invite, "expires_at", None),
        is_vanity=is_vanity,
        verification_level=verification_level,
    )


class InviteResolver:
    """Resolves Discord invite codes via the Discord HTTP API with a TTL+LRU cache.

    Failures (NotFound, HTTPException, timeout, unexpected errors) are converted
    into an unresolved InviteView. Both resolved and unresolved entries are
    cached; unresolved entries get a shorter TTL (`min(ttl_seconds, 60)`).
    """

    def __init__(
        self,
        client: object,
        ttl_seconds: int = 600,
        max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._unresolved_ttl_seconds = min(ttl_seconds, 60)
        self._max_entries = max_entries
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        # code -> (view, inserted_at, entry_ttl)
        self._cache: OrderedDict[str, tuple[InviteView, float, float]] = OrderedDict()

    async def resolve(self, code: str) -> InviteView:
        now = self._clock()
        cached = self._cache.get(code)
        if cached is not None:
            view, inserted_at, entry_ttl = cached
            if now - inserted_at < entry_ttl:
                return view
            # Expired: drop and refetch.
            del self._cache[code]

        try:
            invite = await asyncio.wait_for(
                self._client.fetch_invite(
                    code, with_counts=True, with_expiration=True
                ),
                timeout=self._timeout_seconds,
            )
            view = _build_view(code, invite)
            entry_ttl = float(self._ttl_seconds)
        except discord.NotFound:
            logger.info("invite not found: %s", code)
            view = InviteView(code=code, resolved=False)
            entry_ttl = float(self._unresolved_ttl_seconds)
        except discord.HTTPException:
            logger.info("invite HTTP error for %s", code)
            view = InviteView(code=code, resolved=False)
            entry_ttl = float(self._unresolved_ttl_seconds)
        except asyncio.TimeoutError:
            logger.info("invite resolution timed out: %s", code)
            view = InviteView(code=code, resolved=False)
            entry_ttl = float(self._unresolved_ttl_seconds)
        except Exception:
            logger.exception("invite resolution failed: %s", code)
            view = InviteView(code=code, resolved=False)
            entry_ttl = float(self._unresolved_ttl_seconds)

        self._cache[code] = (view, self._clock(), entry_ttl)
        # Move to most-recently-inserted position (it already is by OrderedDict
        # semantics for new keys, but be explicit in case of races).
        self._cache.move_to_end(code)

        # LRU eviction: drop oldest insertion until at/under bound.
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

        return view
