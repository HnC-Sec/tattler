from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)


_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_MAX_COLOR = 0xFFFFFF

_VERIFICATION_LEVELS = frozenset({"none", "low", "medium", "high", "highest"})


class GlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    default_rate_limit_seconds: int = 30
    embed_author: str = "Tattler bot"
    invite_cache_ttl_seconds: int = 600
    invite_cache_max_entries: int = 1024


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


class _RuleBase(BaseModel):
    """Fields shared by every rule variant. Not instantiated directly."""

    model_config = ConfigDict(extra="forbid")

    name: str
    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    rate_limit_seconds: int | None = None
    message: str | None = None
    webhooks: list[str] = Field(min_length=1)
    embed: EmbedConfig | None = None

    @model_validator(mode="after")
    def _require_message_or_embed_description(self):
        if not self.message and not (self.embed and self.embed.description):
            raise ValueError(
                "rule must define either `message` or `embed.description`"
            )
        return self

    def effective_rate_limit(self, globals_: GlobalConfig) -> int:
        return (
            self.rate_limit_seconds
            if self.rate_limit_seconds is not None
            else globals_.default_rate_limit_seconds
        )


class MessageRuleConfig(_RuleBase):
    """Regex rule matched against the searchable text of every observed message."""

    type: Literal["message"] = "message"
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v

    @property
    def compiled_pattern(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


class InviteRuleConfig(_RuleBase):
    """Rule matched against Discord invites detected in observed messages."""

    type: Literal["invite"]
    pattern: str | None = None
    target_guild_include: list[int] = Field(default_factory=list)
    target_guild_exclude: list[int] = Field(default_factory=list)
    min_members: int | None = None
    max_members: int | None = None
    vanity: bool | None = None
    has_expiry: bool | None = None
    verification_level: list[str] = Field(default_factory=list)
    match_unresolved: bool = False

    @field_validator("pattern")
    @classmethod
    def _validate_optional_pattern(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v

    @field_validator("verification_level")
    @classmethod
    def _validate_verification_levels(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in _VERIFICATION_LEVELS]
        if bad:
            raise ValueError(
                f"invalid verification_level value(s): {bad!r}; "
                f"allowed: {sorted(_VERIFICATION_LEVELS)}"
            )
        return v

    @model_validator(mode="after")
    def _validate_invite_rule(self):
        if (
            self.min_members is not None
            and self.max_members is not None
            and self.min_members > self.max_members
        ):
            raise ValueError("min_members must be <= max_members")

        resolution_dependent = (
            self.target_guild_include
            or self.target_guild_exclude
            or self.min_members is not None
            or self.max_members is not None
            or self.vanity is not None
            or self.has_expiry is not None
            or self.verification_level
        )
        unresolved_safe = self.pattern is not None
        if not resolution_dependent and not unresolved_safe:
            raise ValueError(
                "invite rule must define at least one condition "
                "(pattern, target_guild_include/exclude, min/max_members, "
                "vanity, has_expiry, or verification_level)"
            )
        if self.match_unresolved and not unresolved_safe:
            raise ValueError(
                "match_unresolved: true requires a `pattern` condition "
                "(other invite conditions are skipped for unresolved invites)"
            )
        return self

    @property
    def compiled_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.pattern) if self.pattern is not None else None


def _rule_type_tag(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("type", "message")
    return getattr(v, "type", "message")


RuleConfig = Annotated[
    Union[
        Annotated[MessageRuleConfig, Tag("message")],
        Annotated[InviteRuleConfig, Tag("invite")],
    ],
    Discriminator(_rule_type_tag),
]


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
                raise ValueError(
                    f"rule {rule.name!r} references undefined webhooks: {sorted(unknown)}"
                )
        return self
