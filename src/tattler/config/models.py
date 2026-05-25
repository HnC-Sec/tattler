from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    default_rate_limit_seconds: int = 30


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    format: Literal["generic", "discord"]
    timeout_seconds: float = 5.0
    retries: int = 3
    backoff_base_seconds: float = 1.0


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pattern: str
    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    rate_limit_seconds: int | None = None
    message: str
    webhooks: list[str] = Field(min_length=1)

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
