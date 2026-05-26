# Discord Embed Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send Discord webhook notifications as embeds (with per-rule overrides and a global `embed_author` default) instead of plain `{"content": ...}` payloads.

**Architecture:** Add an `EmbedConfig` pydantic model and an optional `embed:` block on `RuleConfig`. Unify all formatters under one signature `format(event, rule, globals)` so each formatter renders the templates it needs. `DiscordFormatter` builds an `{"embeds": [...]}` payload, falling back to sensible defaults (rule name, the rule's `message`, the message link, the global author). The `NotifierWorker` resolves the current `RuleConfig` from the live config at dispatch time and passes it to each formatter.

**Tech Stack:** Python 3, pydantic v2, httpx, pytest + pytest-asyncio + respx.

**Spec:** `docs/superpowers/specs/2026-05-25-discord-embeds-design.md`

---

### Task 1: Add `EmbedConfig` model and `globals.embed_author`

**Files:**
- Modify: `src/tattler/config/models.py`
- Modify: `tests/unit/test_config_models.py`

- [ ] **Step 1: Write the failing test for `EmbedConfig` parsing + defaults**

Add to `tests/unit/test_config_models.py`:

```python
from tattler.config.models import Config, EmbedConfig, GlobalConfig, RuleConfig, WebhookConfig


def test_embed_config_parses_all_fields_and_normalizes_color_hex_string():
    embed = EmbedConfig.model_validate({
        "title": "{rule_name}",
        "description": "{content}",
        "url": "{message_link}",
        "author": "Bot",
        "color": "#ff5555",
        "footer": "from {guild_name}",
    })
    assert embed.title == "{rule_name}"
    assert embed.description == "{content}"
    assert embed.url == "{message_link}"
    assert embed.author == "Bot"
    assert embed.color == 0xFF5555
    assert embed.footer == "from {guild_name}"


def test_embed_config_color_accepts_0x_prefix_and_uppercase():
    assert EmbedConfig.model_validate({"color": "0xFF5555"}).color == 0xFF5555
    assert EmbedConfig.model_validate({"color": "#FF5555"}).color == 0xFF5555


def test_embed_config_color_accepts_integer():
    assert EmbedConfig.model_validate({"color": 16734293}).color == 16734293


def test_embed_config_rejects_malformed_color():
    for bad in ["red", "#zzzzzz", "#fffffff", "#fff", -1, 0x1000000]:
        with pytest.raises(ValidationError):
            EmbedConfig.model_validate({"color": bad})


def test_embed_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        EmbedConfig.model_validate({"thumbnail": "https://example.com/x.png"})


def test_globals_embed_author_defaults_to_tattler_bot():
    g = GlobalConfig()
    assert g.embed_author == "Tattler bot"


def test_globals_embed_author_can_be_overridden():
    g = GlobalConfig.model_validate({"embed_author": "MyBot"})
    assert g.embed_author == "MyBot"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/unit/test_config_models.py -v`
Expected: ImportError or AttributeError for `EmbedConfig`; failures for the new test names.

- [ ] **Step 3: Add `EmbedConfig` and `embed_author` to `src/tattler/config/models.py`**

Replace the file contents with:

```python
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_MAX_COLOR = 0xFFFFFF


class GlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    default_rate_limit_seconds: int = 30
    embed_author: str = "Tattler bot"


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    format: Literal["generic", "discord"]
    timeout_seconds: float = 5.0
    retries: int = 3
    backoff_base_seconds: float = 1.0


class EmbedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    url: str | None = None
    author: str | None = None
    color: int | None = None
    footer: str | None = None

    @field_validator("color", mode="before")
    @classmethod
    def _normalize_color(cls, v):
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("color must be an int or hex string, not bool")
        if isinstance(v, int):
            if not 0 <= v <= _MAX_COLOR:
                raise ValueError(f"color int out of range 0..0xFFFFFF: {v}")
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("#"):
                s = s[1:]
            elif s.startswith(("0x", "0X")):
                s = s[2:]
            if not _HEX_RE.fullmatch(s):
                raise ValueError(f"invalid hex color: {v!r}")
            return int(s, 16)
        raise ValueError(f"unsupported color type: {type(v).__name__}")


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pattern: str
    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    rate_limit_seconds: int | None = None
    message: str | None = None
    webhooks: list[str] = Field(min_length=1)
    embed: EmbedConfig | None = None

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v

    @model_validator(mode="after")
    def _require_message_or_embed_description(self) -> "RuleConfig":
        if not self.message and not (self.embed and self.embed.description):
            raise ValueError(
                "rule must define either `message` or `embed.description`"
            )
        return self

    @property
    def compiled_pattern(self) -> re.Pattern[str]:
        return re.compile(self.pattern)

    def effective_rate_limit(self, globals_: GlobalConfig) -> int:
        return self.rate_limit_seconds if self.rate_limit_seconds is not None else globals_.default_rate_limit_seconds


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    globals: GlobalConfig = Field(default_factory=GlobalConfig)
    webhooks: dict[str, WebhookConfig]
    rules: list[RuleConfig]

    @model_validator(mode="after")
    def _cross_validate(self) -> "Config":
        names = [r.name for r in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("duplicate rule names")
        known = set(self.webhooks)
        for rule in self.rules:
            unknown = set(rule.webhooks) - known
            if unknown:
                raise ValueError(f"rule {rule.name!r} references undefined webhooks: {sorted(unknown)}")
        return self
```

- [ ] **Step 4: Run the new model tests and confirm they pass**

Run: `uv run pytest tests/unit/test_config_models.py -v`
Expected: all previously-failing new tests now PASS. All previously-passing tests still PASS.

- [ ] **Step 5: Write the failing test for message/embed.description requirement**

Append to `tests/unit/test_config_models.py`:

```python
def test_rule_message_optional_when_embed_description_set():
    d = _minimal_dict()
    d["rules"][0].pop("message")
    d["rules"][0]["embed"] = {"description": "{content}"}
    cfg = Config.model_validate(d)
    assert cfg.rules[0].message is None
    assert cfg.rules[0].embed.description == "{content}"


def test_rule_rejects_when_both_message_and_embed_description_missing():
    d = _minimal_dict()
    d["rules"][0].pop("message")
    d["rules"][0]["embed"] = {"title": "t"}
    with pytest.raises(ValidationError):
        Config.model_validate(d)


def test_rule_rejects_when_message_and_embed_both_missing():
    d = _minimal_dict()
    d["rules"][0].pop("message")
    with pytest.raises(ValidationError):
        Config.model_validate(d)
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `uv run pytest tests/unit/test_config_models.py -v`
Expected: all PASS (the validator from Step 3 already covers this).

- [ ] **Step 7: Run the full test suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: all PASS (existing behavior unchanged because `message` is still provided by every existing fixture).

- [ ] **Step 8: Commit**

```bash
git add src/tattler/config/models.py tests/unit/test_config_models.py
git commit -m "feat(config): add EmbedConfig model and globals.embed_author"
```

---

### Task 2: Unify formatter signature to `format(event, rule, globals)`

**Files:**
- Modify: `src/tattler/notifier/webhooks/base.py`
- Modify: `src/tattler/notifier/webhooks/generic.py`
- Modify: `src/tattler/notifier/webhooks/discord.py`
- Modify: `tests/unit/test_webhooks_generic.py`
- Modify: `tests/unit/test_webhooks_discord.py`

This task only changes the signature; behavior is preserved (Discord still emits `{"content": ...}` for now — Task 4 swaps it to embeds).

- [ ] **Step 1: Update the existing generic formatter test to the new signature**

Replace `tests/unit/test_webhooks_generic.py` with:

```python
from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.webhooks.generic import GenericFormatter


def _cfg() -> Config:
    return Config.model_validate({
        "webhooks": {
            "audit": {"url": "https://x", "format": "generic", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "hi", "message": "rendered: {content}", "webhooks": ["audit"]},
        ],
    })


def _event() -> MatchEvent:
    return MatchEvent(
        rule_name="r1",
        rule_webhooks=("audit",),
        rule_message_template="rendered: {content}",
        rule_rate_limit_seconds=30,
        author="alice",
        author_id=111,
        channel_name="general",
        channel_id=222,
        guild_name="srv",
        guild_id=333,
        content="hi",
        message_id=444,
        message_link="https://discord.com/channels/333/222/444",
        timestamp=datetime(2026, 5, 25, 14, 23, 0, tzinfo=timezone.utc),
        is_edit=False,
        match="hi",
        match_groups=("hi",),
    )


def test_generic_payload_shape_renders_rule_message():
    cfg = _cfg()
    payload = GenericFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {
        "rule_name": "r1",
        "message": "rendered: hi",
        "event": {
            "author": "alice",
            "author_id": "111",
            "channel_name": "general",
            "channel_id": "222",
            "guild_name": "srv",
            "guild_id": "333",
            "content": "hi",
            "message_id": "444",
            "message_link": "https://discord.com/channels/333/222/444",
            "timestamp": "2026-05-25T14:23:00+00:00",
            "match": "hi",
            "match_groups": ["hi"],
            "is_edit": False,
        },
    }


def test_generic_payload_falls_back_to_embed_description_when_message_absent():
    cfg = Config.model_validate({
        "webhooks": {
            "audit": {"url": "https://x", "format": "generic", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "hi", "webhooks": ["audit"], "embed": {"description": "embed: {content}"}},
        ],
    })
    payload = GenericFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload["message"] == "embed: hi"
```

- [ ] **Step 2: Update the existing discord formatter test to the new signature (still expects `{"content": ...}` for now — Task 4 changes this)**

Replace `tests/unit/test_webhooks_discord.py` with:

```python
from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.webhooks.discord import DiscordFormatter


def _cfg() -> Config:
    return Config.model_validate({
        "webhooks": {
            "alerts": {"url": "https://x", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [
            {"name": "r1", "pattern": "hi", "message": "rendered: {content}", "webhooks": ["alerts"]},
        ],
    })


def _event() -> MatchEvent:
    return MatchEvent(
        rule_name="r1",
        rule_webhooks=("alerts",),
        rule_message_template="rendered: {content}",
        rule_rate_limit_seconds=30,
        author="alice",
        author_id=111,
        channel_name="general",
        channel_id=222,
        guild_name="srv",
        guild_id=333,
        content="hi",
        message_id=444,
        message_link="https://discord.com/channels/333/222/444",
        timestamp=datetime(2026, 5, 25, 14, 23, 0, tzinfo=timezone.utc),
        is_edit=False,
        match="hi",
        match_groups=("hi",),
    )


def test_discord_payload_still_content_for_now():
    cfg = _cfg()
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {"content": "rendered: hi"}
```

- [ ] **Step 3: Run the formatter tests and confirm they fail**

Run: `uv run pytest tests/unit/test_webhooks_generic.py tests/unit/test_webhooks_discord.py -v`
Expected: FAIL with TypeError (formatter still uses old `(event, rendered_message)` signature).

- [ ] **Step 4: Update the `WebhookFormatter` protocol**

Replace `src/tattler/notifier/webhooks/base.py` with:

```python
from __future__ import annotations

from typing import Any, Protocol

from tattler.config.models import GlobalConfig, RuleConfig
from tattler.events import MatchEvent


class WebhookFormatter(Protocol):
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        ...
```

- [ ] **Step 5: Update `GenericFormatter` to new signature**

Replace `src/tattler/notifier/webhooks/generic.py` with:

```python
from __future__ import annotations

from typing import Any

from tattler.config.models import GlobalConfig, RuleConfig
from tattler.events import MatchEvent
from tattler.notifier.template import render


class GenericFormatter:
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        template = rule.message
        if template is None:
            # Validator on RuleConfig guarantees embed.description is set when message is None.
            template = rule.embed.description  # type: ignore[union-attr]
        rendered = render(template, event)
        return {
            "rule_name": event.rule_name,
            "message": rendered,
            "event": {
                "author": event.author,
                "author_id": str(event.author_id),
                "channel_name": event.channel_name,
                "channel_id": str(event.channel_id),
                "guild_name": event.guild_name,
                "guild_id": "" if event.guild_id is None else str(event.guild_id),
                "content": event.content,
                "message_id": str(event.message_id),
                "message_link": event.message_link,
                "timestamp": event.timestamp.isoformat(),
                "match": event.match,
                "match_groups": list(event.match_groups),
                "is_edit": event.is_edit,
            },
        }
```

- [ ] **Step 6: Update `DiscordFormatter` to new signature (still emits `content` for now)**

Replace `src/tattler/notifier/webhooks/discord.py` with:

```python
from __future__ import annotations

from typing import Any

from tattler.config.models import GlobalConfig, RuleConfig
from tattler.events import MatchEvent
from tattler.notifier.template import render


class DiscordFormatter:
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals_: GlobalConfig,
    ) -> dict[str, Any]:
        # Temporary: preserved behavior. Task 4 replaces this with embed rendering.
        template = rule.message or (rule.embed.description if rule.embed else "")
        return {"content": render(template, event)}
```

- [ ] **Step 7: Run the formatter tests and confirm they pass**

Run: `uv run pytest tests/unit/test_webhooks_generic.py tests/unit/test_webhooks_discord.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the full suite — worker / integration will fail until Task 3, that's expected**

Run: `uv run pytest -q`
Expected: failures in `test_notifier_worker.py` and `test_pipeline.py` (TypeError calling the formatters with the old `(event, rendered_message)` signature from inside `NotifierWorker`). Note them and proceed to Task 3.

- [ ] **Step 9: Commit**

```bash
git add src/tattler/notifier/webhooks/base.py src/tattler/notifier/webhooks/generic.py src/tattler/notifier/webhooks/discord.py tests/unit/test_webhooks_generic.py tests/unit/test_webhooks_discord.py
git commit -m "refactor(webhooks): unify formatter signature to (event, rule, globals)"
```

---

### Task 3: Update `NotifierWorker` to resolve the rule and pass it to formatters

**Files:**
- Modify: `src/tattler/notifier/worker.py`
- Modify: `tests/unit/test_notifier_worker.py`

- [ ] **Step 1: Add a failing test for unknown-rule drop behavior**

Append to `tests/unit/test_notifier_worker.py`:

```python
@respx.mock
async def test_worker_drops_event_for_unknown_rule_name(caplog):
    respx.post("https://example.com/alerts").mock(return_value=httpx.Response(204))
    respx.post("https://example.com/audit").mock(return_value=httpx.Response(204))

    bus = EventBus()
    cfg_holder = lambda: _cfg()
    async with httpx.AsyncClient() as client:
        worker = NotifierWorker(bus, cfg_holder, client)
        task = asyncio.create_task(worker.run())
        await bus.publish(_event(rule_name="vanished"))
        await asyncio.wait_for(bus.join(), timeout=1.0)
        worker.stop()
        await task

    assert len(respx.calls) == 0
```

- [ ] **Step 2: Run the existing worker tests and confirm two-failure mode**

Run: `uv run pytest tests/unit/test_notifier_worker.py -v`
Expected: `test_worker_dispatches_to_all_named_webhooks_for_event` FAILS (TypeError from formatter signature mismatch); new `test_worker_drops_event_for_unknown_rule_name` FAILS (no unknown-rule handling yet).

- [ ] **Step 3: Update `src/tattler/notifier/worker.py`**

Replace the file with:

```python
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
```

- [ ] **Step 4: Run worker tests and confirm they pass**

Run: `uv run pytest tests/unit/test_notifier_worker.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite — integration test may still fail; check**

Run: `uv run pytest -q`
Expected: `tests/integration/test_pipeline.py` still passes (its assertion `b"alice said hello in #general" in body` matches against the `{"content": "..."}` payload which still works after Task 2). All unit tests PASS.

If the integration test fails, stop and inspect; do not proceed.

- [ ] **Step 6: Commit**

```bash
git add src/tattler/notifier/worker.py tests/unit/test_notifier_worker.py
git commit -m "refactor(notifier): worker resolves rule from config and drops on unknown"
```

---

### Task 4: Implement Discord embed rendering

**Files:**
- Modify: `src/tattler/notifier/webhooks/discord.py`
- Modify: `tests/unit/test_webhooks_discord.py`

- [ ] **Step 1: Replace the discord formatter test with embed-shape coverage**

Replace `tests/unit/test_webhooks_discord.py` with:

```python
from datetime import datetime, timezone

from tattler.config.models import Config
from tattler.events import MatchEvent
from tattler.notifier.webhooks.discord import DiscordFormatter


def _event(**overrides) -> MatchEvent:
    defaults = dict(
        rule_name="r1",
        rule_webhooks=("alerts",),
        rule_message_template="rendered: {content}",
        rule_rate_limit_seconds=30,
        author="alice",
        author_id=111,
        channel_name="general",
        channel_id=222,
        guild_name="srv",
        guild_id=333,
        content="hi",
        message_id=444,
        message_link="https://discord.com/channels/333/222/444",
        timestamp=datetime(2026, 5, 25, 14, 23, 0, tzinfo=timezone.utc),
        is_edit=False,
        match="hi",
        match_groups=("hi",),
    )
    defaults.update(overrides)
    return MatchEvent(**defaults)


def _cfg(rule_overrides=None, globals_overrides=None) -> Config:
    rule = {"name": "r1", "pattern": "hi", "message": "rendered: {content}", "webhooks": ["alerts"]}
    if rule_overrides:
        rule.update(rule_overrides)
    cfg_dict = {
        "webhooks": {
            "alerts": {"url": "https://x", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [rule],
    }
    if globals_overrides:
        cfg_dict["globals"] = globals_overrides
    return Config.model_validate(cfg_dict)


def test_default_embed_uses_rule_name_message_link_and_global_author():
    cfg = _cfg()
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {
        "embeds": [
            {
                "title": "r1",
                "description": "rendered: hi",
                "url": "https://discord.com/channels/333/222/444",
                "author": {"name": "Tattler bot"},
            }
        ]
    }


def test_global_embed_author_override_is_used():
    cfg = _cfg(globals_overrides={"embed_author": "MyBot"})
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload["embeds"][0]["author"] == {"name": "MyBot"}


def test_per_rule_overrides_replace_each_default_and_render_templates():
    cfg = _cfg(rule_overrides={
        "embed": {
            "title": "Alert: {rule_name}",
            "description": "{author} said {content}",
            "url": "https://example.com/{message_id}",
            "author": "{guild_name}",
            "color": "#ff5555",
            "footer": "in #{channel_name}",
        }
    })
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload == {
        "embeds": [
            {
                "title": "Alert: r1",
                "description": "alice said hi",
                "url": "https://example.com/444",
                "author": {"name": "srv"},
                "color": 0xFF5555,
                "footer": {"text": "in #general"},
            }
        ]
    }


def test_color_only_override_keeps_all_other_defaults():
    cfg = _cfg(rule_overrides={"embed": {"color": 0x00FF00}})
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    embed = payload["embeds"][0]
    assert embed["title"] == "r1"
    assert embed["description"] == "rendered: hi"
    assert embed["url"] == "https://discord.com/channels/333/222/444"
    assert embed["author"] == {"name": "Tattler bot"}
    assert embed["color"] == 0x00FF00


def test_empty_rendered_field_is_omitted_so_user_can_suppress_default():
    cfg = _cfg(rule_overrides={"embed": {"url": "", "author": ""}})
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    embed = payload["embeds"][0]
    assert "url" not in embed
    assert "author" not in embed
    assert embed["title"] == "r1"
    assert embed["description"] == "rendered: hi"


def test_description_falls_back_to_embed_description_when_message_absent():
    cfg = _cfg(rule_overrides={"message": None, "embed": {"description": "embed: {content}"}})
    # model_validate strips message=None as omitted; re-validate explicitly:
    cfg_dict = {
        "webhooks": {
            "alerts": {"url": "https://x", "format": "discord", "timeout_seconds": 1, "retries": 0, "backoff_base_seconds": 0.0},
        },
        "rules": [{"name": "r1", "pattern": "hi", "webhooks": ["alerts"], "embed": {"description": "embed: {content}"}}],
    }
    cfg = Config.model_validate(cfg_dict)
    payload = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)
    assert payload["embeds"][0]["description"] == "embed: hi"


def test_footer_default_omitted_when_not_specified():
    cfg = _cfg()
    embed = DiscordFormatter().format(_event(), cfg.rules[0], cfg.globals)["embeds"][0]
    assert "footer" not in embed
    assert "color" not in embed
```

- [ ] **Step 2: Run the discord tests and confirm they fail**

Run: `uv run pytest tests/unit/test_webhooks_discord.py -v`
Expected: most tests FAIL (current formatter still emits `{"content": ...}`).

- [ ] **Step 3: Rewrite `src/tattler/notifier/webhooks/discord.py`**

Replace the file with:

```python
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

        # description — default: rendered rule.message; override: rendered embed.description
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
```

- [ ] **Step 4: Run the discord tests and confirm they pass**

Run: `uv run pytest tests/unit/test_webhooks_discord.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite — the existing integration test will fail and that's expected; fix in Task 5**

Run: `uv run pytest -q`
Expected: `tests/integration/test_pipeline.py::test_happy_path_pipeline` FAILS (it asserts the literal substring `b"alice said hello in #general"`, which is now inside an embed JSON body — and still passes because JSON serializes the string in `description`). Verify the assertion actually still matches; if so the test continues to pass and Task 5 only needs to update the example config + add embed-aware assertions. If it fails, Task 5 fixes it.

- [ ] **Step 6: Commit**

```bash
git add src/tattler/notifier/webhooks/discord.py tests/unit/test_webhooks_discord.py
git commit -m "feat(discord): render webhook notifications as embeds"
```

---

### Task 5: Update integration test and example config

**Files:**
- Modify: `tests/integration/test_pipeline.py`
- Modify: `config.example.yaml`

- [ ] **Step 1: Replace the happy-path integration assertion with an embed-aware assertion**

In `tests/integration/test_pipeline.py`, replace the body of `test_happy_path_pipeline` after the `worker.stop(); await task` block with:

```python
    assert route.call_count == 1
    import json
    body = json.loads(route.calls.last.request.read())
    assert body == {
        "embeds": [
            {
                "title": "say_hi",
                "description": "alice said hello in #general",
                "url": "https://discord.com/x",
                "author": {"name": "Tattler bot"},
            }
        ]
    }
```

(Move the `import json` to the top of the file if you prefer; either placement runs.)

- [ ] **Step 2: Run the integration test and confirm it passes**

Run: `uv run pytest tests/integration/test_pipeline.py -v`
Expected: all PASS.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 4: Update `config.example.yaml`**

Replace the `globals:` block in `config.example.yaml` with:

```yaml
globals:
  # Optional allowlist. If non-empty, a message must have at least one
  # matching snowflake (guild, channel, author, or role) to be eligible.
  include: []

  # Optional denylist. If a message has any snowflake here, it is skipped.
  # Common uses: ignore yourself (the self-bot's own user ID), ignore noisy
  # bot channels, ignore a specific server entirely.
  exclude: []
    # - 111111111111111111   # your own user ID (highly recommended)
    # - 222222222222222222   # a noisy #bot-spam channel

  # Default cooldown applied to rules that don't specify their own
  # rate_limit_seconds. Keyed by (rule name, channel) — a hit in one channel
  # won't suppress the same rule firing in another.
  default_rate_limit_seconds: 30

  # Default `author.name` for Discord embed payloads. Per-rule
  # `embed.author` overrides this.
  embed_author: "Tattler bot"
```

Then append an updated rules section that demonstrates the embed block. Replace the existing `rules:` block with:

```yaml
rules:
  # Example 1: alert when someone mentions you by name.
  # Discord webhooks now send rich embeds. All embed fields are optional;
  # by default the embed shows: title=rule name, description=`message`,
  # url=message link, author=globals.embed_author. Override any field below.
  # Strings support the same {placeholders} as `message`. Set a field to "" to
  # suppress its default.
  - name: name_mention
    pattern: "(?i)\\b(javert|harry|skelli)\\b"
    rate_limit_seconds: 60
    message: "{author} mentioned you in #{channel_name} ({guild_name}): {content}\n{message_link}"
    webhooks: [alerts]
    exclude:
      - 135499198865997824
    embed:
      color: "#ff5555"
      footer: "matched: {match}"
```

- [ ] **Step 5: Sanity-check that the example config loads**

Run:
```bash
uv run python -c "import yaml; from tattler.config.models import Config; Config.model_validate(yaml.safe_load(open('config.example.yaml')))"
```
Expected: no output (no exception).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_pipeline.py config.example.yaml
git commit -m "test+docs: integration test asserts embed shape; example config shows embed block"
```

---

### Task 6: Remove dead `rule_message_template` field from `MatchEvent`

The worker now reads the rule from live config and the formatter has direct access to `rule.message` — `MatchEvent.rule_message_template` is no longer read by any code path.

**Files:**
- Modify: `src/tattler/events.py`
- Modify: `src/tattler/matcher.py`
- Modify: `tests/unit/test_notifier_worker.py`
- Modify: `tests/unit/test_webhooks_discord.py`
- Modify: `tests/unit/test_webhooks_generic.py`

- [ ] **Step 1: Confirm nothing reads the field**

Run: `grep -rn "rule_message_template" src tests`
Expected: matches are limited to (a) the `MatchEvent` definition, (b) the matcher's `yield MatchEvent(...)` call, and (c) test fixtures that construct `MatchEvent`. There must be NO consumer reading `event.rule_message_template`.

If a consumer exists, stop and route the work back to design — do not blindly delete.

- [ ] **Step 2: Remove the field from `src/tattler/events.py`**

Edit `src/tattler/events.py` to delete the `rule_message_template: str` line:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class MatchEvent:
    """Emitted by the matcher when a regex rule matches a message."""

    rule_name: str
    rule_webhooks: tuple[str, ...]
    rule_rate_limit_seconds: int

    # Discord context
    author: str
    author_id: int
    channel_name: str
    channel_id: int
    guild_name: str
    guild_id: int | None
    content: str
    message_id: int
    message_link: str
    timestamp: datetime
    is_edit: bool

    # Match data
    match: str
    match_groups: tuple[str, ...] = field(default_factory=tuple)
```

- [ ] **Step 3: Remove the field from the matcher**

In `src/tattler/matcher.py`, delete the `rule_message_template=rule.message,` line inside the `yield MatchEvent(...)` block (around line 61).

- [ ] **Step 4: Remove the field from every test fixture that builds a `MatchEvent`**

In each of the following files, delete the `rule_message_template="..."` argument from the `MatchEvent(...)` constructor:
- `tests/unit/test_notifier_worker.py` (`_event` helper)
- `tests/unit/test_webhooks_discord.py` (`_event` helper)
- `tests/unit/test_webhooks_generic.py` (`_event` helper)

- [ ] **Step 5: Run the full suite and confirm it passes**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Re-grep to confirm the field is gone**

Run: `grep -rn "rule_message_template" src tests`
Expected: zero matches.

- [ ] **Step 7: Commit**

```bash
git add src/tattler/events.py src/tattler/matcher.py tests/unit/test_notifier_worker.py tests/unit/test_webhooks_discord.py tests/unit/test_webhooks_generic.py
git commit -m "refactor(events): drop unused rule_message_template snapshot from MatchEvent"
```

---

## Self-Review Notes

Spec coverage:
- Global `embed_author` default — Task 1
- Per-rule `embed:` block w/ title/description/url/author/color/footer — Task 1 (model), Task 4 (rendering)
- Color hex/int/0x normalization & validation — Task 1
- `message` optional iff `embed.description` set — Task 1
- Unified formatter signature `(event, rule, globals)` — Task 2
- DiscordFormatter builds `{"embeds":[...]}` with defaults & overrides — Task 4
- Empty rendered field omitted (suppression) — Task 4 (covered by test)
- GenericFormatter unchanged in shape; falls back to embed.description when message absent — Task 2
- Worker resolves rule from current config; drops on unknown — Task 3
- Example config updated — Task 5
- Integration test updated to embed shape — Task 5
- Cleanup of dead `rule_message_template` snapshot — Task 6
