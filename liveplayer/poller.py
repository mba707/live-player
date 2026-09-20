from __future__ import annotations

import asyncio
import logging

from liveplayer.models import Channel, ChannelSnapshot
from liveplayer.platforms.base import ChannelLookupError
from liveplayer.platforms.registry import PlatformRegistry
from liveplayer.store import ChannelStore

logger = logging.getLogger(__name__)


class StreamPoller:
    def __init__(self, store: ChannelStore, registry: PlatformRegistry, interval: int):
        self.store = store
        self.registry = registry
        self.interval = interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="stream-poller")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def refresh_all(self) -> None:
        channels = await self.store.list()
        if not channels:
            return
        results = await self.registry.refresh(channels)
        processed: set[tuple[str, str]] = set()
        for channel in channels:
            result = results.get(channel.id)
            if isinstance(result, Exception):
                message = (
                    str(result)
                    if isinstance(result, ChannelLookupError)
                    else f"Refresh failed: {result}"
                )
                logger.warning("Refresh error for %s: %s", channel.username, message)
                await self.store.mark_error(channel.id, message)
                continue
            if result is None:
                continue
            source = channel.source_key()
            if source in processed:
                continue
            processed.add(source)
            await self.store.replace_source_streams(channel, result)

    async def refresh_one(self, channel_id: str) -> Channel | ChannelSnapshot | None:
        channel = await self.store.get(channel_id)
        if channel is None:
            return None
        resolved = await self.registry.resolve(channel.platform, channel.username)
        updated = await self.store.replace_source_streams(channel, resolved)
        if updated:
            return updated[0]
        return resolved.snapshot

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh_all()
            except Exception:  # noqa: BLE001
                logger.exception("Poller cycle failed")
            await asyncio.sleep(self.interval)
