from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from tattler.invites import InviteResolver, InviteView


# ---------- Test scaffolding ----------


class Clock:
    """Mutable monotonic-style clock for deterministic TTL tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeVerificationLevel:
    name: str


def make_invite(
    code: str = "abc",
    *,
    guild_id: int | None = 111,
    guild_name: str = "Cool Guild",
    guild_features: tuple[str, ...] | None = ("COMMUNITY", "VERIFIED"),
    vanity_url_code: str | None = None,
    verification_level_name: str | None = "low",
    channel_id: int | None = 222,
    channel_name: str = "general",
    inviter_id: int | None = 333,
    inviter_name: str = "alice",
    member_count: int | None = 100,
    presence_count: int | None = 50,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    guild: Any
    if guild_id is None and guild_name == "" and guild_features is None and vanity_url_code is None:
        guild = None
    else:
        kwargs: dict[str, Any] = {
            "id": guild_id,
            "name": guild_name,
            "vanity_url_code": vanity_url_code,
        }
        if guild_features is not None:
            kwargs["features"] = list(guild_features)
        if verification_level_name is not None:
            kwargs["verification_level"] = FakeVerificationLevel(verification_level_name)
        else:
            kwargs["verification_level"] = None
        guild = SimpleNamespace(**kwargs)

    channel = (
        SimpleNamespace(id=channel_id, name=channel_name)
        if channel_id is not None or channel_name
        else None
    )
    inviter = (
        SimpleNamespace(id=inviter_id, name=inviter_name)
        if inviter_id is not None or inviter_name
        else None
    )

    return SimpleNamespace(
        code=code,
        guild=guild,
        channel=channel,
        inviter=inviter,
        approximate_member_count=member_count,
        approximate_presence_count=presence_count,
        expires_at=expires_at,
    )


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, Any] = {}
        self.default: Any = None
        self.exception: BaseException | None = None
        self.exception_per_code: dict[str, BaseException] = {}

    def set_response(self, code: str, invite: Any) -> None:
        self.responses[code] = invite

    def raise_for(self, code: str, exc: BaseException) -> None:
        self.exception_per_code[code] = exc

    async def fetch_invite(self, code: str, **kwargs: Any) -> Any:
        self.calls.append((code, kwargs))
        if code in self.exception_per_code:
            raise self.exception_per_code[code]
        if self.exception is not None:
            raise self.exception
        if code in self.responses:
            return self.responses[code]
        if self.default is not None:
            return self.default
        raise RuntimeError(f"no response configured for code {code!r}")


# ---------- Tests ----------


async def test_cache_miss_calls_fetch_and_returns_view():
    client = FakeClient()
    client.set_response("abc", make_invite(code="abc"))
    clock = Clock()
    resolver = InviteResolver(client, ttl_seconds=600, clock=clock)

    view = await resolver.resolve("abc")

    assert isinstance(view, InviteView)
    assert view.code == "abc"
    assert view.resolved is True
    assert view.guild_id == 111
    assert view.guild_name == "Cool Guild"
    assert view.guild_features == ("COMMUNITY", "VERIFIED")
    assert view.channel_id == 222
    assert view.channel_name == "general"
    assert view.inviter_id == 333
    assert view.inviter_name == "alice"
    assert view.approximate_member_count == 100
    assert view.approximate_presence_count == 50
    assert view.verification_level == "low"
    assert view.is_vanity is False
    assert len(client.calls) == 1
    assert client.calls[0][0] == "abc"
    # fetch_invite was called with with_counts/with_expiration
    assert client.calls[0][1].get("with_counts") is True
    assert client.calls[0][1].get("with_expiration") is True


async def test_cache_hit_skips_second_fetch():
    client = FakeClient()
    client.set_response("abc", make_invite(code="abc"))
    clock = Clock()
    resolver = InviteResolver(client, ttl_seconds=600, clock=clock)

    first = await resolver.resolve("abc")
    second = await resolver.resolve("abc")

    assert first is second  # same cached InviteView instance
    assert len(client.calls) == 1


async def test_ttl_expiry_triggers_refetch():
    client = FakeClient()
    client.set_response("abc", make_invite(code="abc", guild_name="First"))
    clock = Clock()
    resolver = InviteResolver(client, ttl_seconds=600, clock=clock)

    first = await resolver.resolve("abc")
    assert first.guild_name == "First"

    # Within TTL: still cached
    clock.advance(599)
    cached = await resolver.resolve("abc")
    assert cached is first
    assert len(client.calls) == 1

    # Past TTL: re-fetch
    clock.advance(2)
    client.set_response("abc", make_invite(code="abc", guild_name="Second"))
    refetched = await resolver.resolve("abc")
    assert refetched.guild_name == "Second"
    assert len(client.calls) == 2


async def test_lru_eviction_when_exceeding_max_entries():
    client = FakeClient()
    client.default = None
    for code in ("a", "b", "c", "d"):
        client.set_response(code, make_invite(code=code))
    clock = Clock()
    resolver = InviteResolver(client, ttl_seconds=600, max_entries=2, clock=clock)

    await resolver.resolve("a")
    await resolver.resolve("b")
    # cache: [a, b]
    await resolver.resolve("c")
    # cache: [b, c]; "a" evicted

    assert len(client.calls) == 3
    # b still cached
    await resolver.resolve("b")
    assert len(client.calls) == 3
    # a should have been evicted -> refetch
    await resolver.resolve("a")
    assert len(client.calls) == 4


async def test_fetch_raising_generic_exception_returns_unresolved():
    client = FakeClient()
    client.raise_for("bad", RuntimeError("boom"))
    clock = Clock()
    resolver = InviteResolver(client, ttl_seconds=600, clock=clock)

    view = await resolver.resolve("bad")

    assert view.code == "bad"
    assert view.resolved is False
    assert view.guild_id is None
    assert view.guild_name == ""
    assert view.guild_features == ()
    assert view.channel_id is None
    assert view.inviter_id is None
    assert view.approximate_member_count is None
    assert view.verification_level == ""
    assert view.is_vanity is False


async def test_fetch_timeout_returns_unresolved(monkeypatch):
    client = FakeClient()

    async def slow_fetch(code: str, **kwargs: Any) -> Any:
        await asyncio.sleep(10)
        return make_invite(code=code)

    client.fetch_invite = slow_fetch  # type: ignore[assignment]
    clock = Clock()

    # Force wait_for to actually raise TimeoutError quickly by patching it.
    real_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, timeout):
        # Cancel the coro and raise TimeoutError immediately.
        task = asyncio.ensure_future(coro)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):
            pass
        raise asyncio.TimeoutError()

    monkeypatch.setattr("tattler.invites.asyncio.wait_for", fast_wait_for)

    resolver = InviteResolver(client, ttl_seconds=600, clock=clock, timeout_seconds=0.01)
    view = await resolver.resolve("slow")

    assert view.resolved is False
    assert view.code == "slow"

    # restore (monkeypatch handles teardown)
    _ = real_wait_for


async def test_unresolved_sentinel_cached_with_short_ttl():
    client = FakeClient()
    client.raise_for("bad", RuntimeError("boom"))
    clock = Clock()
    resolver = InviteResolver(client, ttl_seconds=600, clock=clock)

    first = await resolver.resolve("bad")
    assert first.resolved is False
    assert len(client.calls) == 1

    # Within unresolved TTL (= min(600, 60) = 60), no refetch.
    clock.advance(59)
    second = await resolver.resolve("bad")
    assert second is first
    assert len(client.calls) == 1

    # Past 60s, refetch happens.
    clock.advance(2)
    await resolver.resolve("bad")
    assert len(client.calls) == 2


async def test_unresolved_ttl_capped_by_ttl_seconds_when_smaller():
    client = FakeClient()
    client.raise_for("bad", RuntimeError("boom"))
    clock = Clock()
    # ttl_seconds=10 < 60, so unresolved TTL should be 10.
    resolver = InviteResolver(client, ttl_seconds=10, clock=clock)

    await resolver.resolve("bad")
    assert len(client.calls) == 1

    clock.advance(9)
    await resolver.resolve("bad")
    assert len(client.calls) == 1

    clock.advance(2)
    await resolver.resolve("bad")
    assert len(client.calls) == 2


async def test_is_vanity_true_when_guild_vanity_matches_code():
    client = FakeClient()
    client.set_response("special", make_invite(code="special", vanity_url_code="special"))
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("special")

    assert view.is_vanity is True


async def test_is_vanity_case_insensitive():
    client = FakeClient()
    client.set_response("MyCode", make_invite(code="MyCode", vanity_url_code="mycode"))
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("MyCode")

    assert view.is_vanity is True


async def test_is_vanity_false_when_codes_differ():
    client = FakeClient()
    client.set_response("abc", make_invite(code="abc", vanity_url_code="zzz"))
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.is_vanity is False


async def test_is_vanity_false_when_no_vanity_url_code():
    client = FakeClient()
    client.set_response("abc", make_invite(code="abc", vanity_url_code=None))
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.is_vanity is False


@pytest.mark.parametrize(
    "name,expected",
    [
        ("none", "none"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("highest", "highest"),
    ],
)
async def test_verification_level_mapping_known(name: str, expected: str):
    client = FakeClient()
    client.set_response(
        "abc", make_invite(code="abc", verification_level_name=name)
    )
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.verification_level == expected


async def test_verification_level_unknown_maps_to_empty_string():
    client = FakeClient()
    client.set_response(
        "abc", make_invite(code="abc", verification_level_name="mystery")
    )
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.verification_level == ""


async def test_resolved_with_none_guild_channel_inviter():
    client = FakeClient()
    invite = SimpleNamespace(
        code="abc",
        guild=None,
        channel=None,
        inviter=None,
        approximate_member_count=None,
        approximate_presence_count=None,
        expires_at=None,
    )
    client.set_response("abc", invite)
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.resolved is True
    assert view.code == "abc"
    assert view.guild_id is None
    assert view.guild_name == ""
    assert view.guild_features == ()
    assert view.channel_id is None
    assert view.channel_name == ""
    assert view.inviter_id is None
    assert view.inviter_name == ""
    assert view.is_vanity is False
    assert view.verification_level == ""


async def test_expires_at_passes_through():
    expiry = datetime(2030, 1, 1, tzinfo=timezone.utc)
    client = FakeClient()
    client.set_response("abc", make_invite(code="abc", expires_at=expiry))
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.expires_at == expiry


async def test_guild_features_missing_defaults_to_empty_tuple():
    client = FakeClient()
    client.set_response(
        "abc", make_invite(code="abc", guild_features=None)
    )
    resolver = InviteResolver(client, clock=Clock())

    view = await resolver.resolve("abc")

    assert view.guild_features == ()
