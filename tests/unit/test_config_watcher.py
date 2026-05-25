import asyncio
from pathlib import Path

import pytest

from tattler.config.watcher import ConfigHolder


def _write(path: Path, webhook_name: str = "alerts") -> None:
    path.write_text(
        f"""
webhooks:
  {webhook_name}:
    url: https://example.com/x
    format: generic
rules:
  - name: r1
    pattern: foo
    message: m
    webhooks: [{webhook_name}]
"""
    )


async def test_initial_load(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write(p)
    holder = ConfigHolder(p)
    holder.load()
    assert "alerts" in holder.get().webhooks


async def test_reload_swaps_on_valid_change(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write(p, "alerts")
    holder = ConfigHolder(p)
    holder.load()
    _write(p, "audit")
    holder.load()
    assert "audit" in holder.get().webhooks
    assert "alerts" not in holder.get().webhooks


async def test_reload_keeps_old_on_invalid_change(tmp_path: Path, caplog):
    p = tmp_path / "c.yaml"
    _write(p, "alerts")
    holder = ConfigHolder(p)
    holder.load()
    p.write_text("not: [valid")  # bad YAML
    with caplog.at_level("ERROR"):
        holder.load()
    assert "alerts" in holder.get().webhooks  # still old config
    assert any("config reload failed" in r.message for r in caplog.records)
