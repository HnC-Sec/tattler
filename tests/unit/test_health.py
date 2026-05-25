import asyncio
from pathlib import Path

from tattler.health import HealthFiles


async def test_touch_live_creates_or_updates_file(tmp_path: Path):
    live = tmp_path / "live"
    ready = tmp_path / "ready"
    h = HealthFiles(live, ready)
    await h.touch_live()
    assert live.exists()


async def test_mark_ready_creates_file(tmp_path: Path):
    live = tmp_path / "live"
    ready = tmp_path / "ready"
    h = HealthFiles(live, ready)
    h.mark_ready()
    assert ready.exists()


async def test_mark_unready_removes_file(tmp_path: Path):
    live = tmp_path / "live"
    ready = tmp_path / "ready"
    h = HealthFiles(live, ready)
    h.mark_ready()
    h.mark_unready()
    assert not ready.exists()


async def test_mark_unready_is_idempotent(tmp_path: Path):
    live = tmp_path / "live"
    ready = tmp_path / "ready"
    h = HealthFiles(live, ready)
    h.mark_unready()  # not present, should not raise
    h.mark_unready()
