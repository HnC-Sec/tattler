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
