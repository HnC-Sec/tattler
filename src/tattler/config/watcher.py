from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchfiles import awatch

from tattler.config.loader import load_config
from tattler.config.models import Config

logger = logging.getLogger(__name__)


class ConfigHolder:
    """Holds the live config; load() (re)reads from disk and atomically swaps on success."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._config: Config | None = None

    def load(self) -> None:
        try:
            new_cfg = load_config(self._path)
        except Exception:
            logger.exception("config reload failed; keeping previous config")
            return
        self._config = new_cfg
        logger.info("config loaded from %s", self._path)

    def get(self) -> Config:
        if self._config is None:
            raise RuntimeError("config not loaded")
        return self._config

    async def watch(self) -> None:
        # Watch the parent directory so we pick up Kubernetes ConfigMap
        # symlink-swap updates (the leaf path itself often doesn't fire).
        parent = self._path.parent
        async for _ in awatch(parent):
            self.load()
