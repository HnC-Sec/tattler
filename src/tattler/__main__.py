from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import httpx

from tattler.bus import EventBus
from tattler.config.watcher import ConfigHolder
from tattler.discord_client import TattlerClient
from tattler.health import HealthFiles
from tattler.notifier.worker import NotifierWorker

logger = logging.getLogger("tattler")


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("TATTLER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _amain() -> int:
    _setup_logging()

    token = os.environ.get("TATTLER_DISCORD_TOKEN")
    if not token:
        logger.error("TATTLER_DISCORD_TOKEN is not set")
        return 2

    config_path = Path(os.environ.get("TATTLER_CONFIG_PATH", "/etc/tattler/config.yaml"))
    health = HealthFiles(
        live_path=Path(os.environ.get("TATTLER_LIVE_PATH", "/tmp/tattler.live")),
        ready_path=Path(os.environ.get("TATTLER_READY_PATH", "/tmp/tattler.ready")),
    )

    holder = ConfigHolder(config_path)
    holder.load()
    try:
        holder.get()
    except RuntimeError:
        logger.error("initial config load failed; exiting")
        return 3

    bus = EventBus()

    async with httpx.AsyncClient() as http:
        worker = NotifierWorker(bus, holder.get, http)
        worker_task = asyncio.create_task(worker.run(), name="notifier-worker")
        watcher_task = asyncio.create_task(holder.watch(), name="config-watcher")
        heartbeat_task = asyncio.create_task(health.heartbeat(), name="health-heartbeat")

        client = TattlerClient(holder.get, bus, health)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        client_task = asyncio.create_task(client.start(token), name="discord-client")
        await stop.wait()

        logger.info("shutdown signal received")
        health.mark_unready()
        await client.close()
        # Drain the bus first (worker still running so task_done() fires).
        try:
            await asyncio.wait_for(bus.join(), timeout=10.0)
        except TimeoutError:
            logger.warning("bus drain timed out")
        worker.stop()
        for t in (worker_task, watcher_task, heartbeat_task, client_task):
            t.cancel()
        for t in (worker_task, watcher_task, heartbeat_task, client_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
