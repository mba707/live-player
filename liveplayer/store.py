from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from liveplayer.models import Channel, ChannelSnapshot, ResolvedChannel, utcnow
from liveplayer.sorting import live_counts, sort_channels


class ChannelStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._channels: dict[str, Channel] = {}
        self.last_refresh: datetime | None = None

    def load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_unlocked([])
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        channels = [Channel.model_validate(item) for item in raw.get("channels", [])]
        self._channels = {channel.id: channel for channel in channels}
        if raw.get("last_refresh"):
            self.last_refresh = datetime.fromisoformat(raw["last_refresh"])

    def _write_unlocked(self, channels: list[Channel] | None = None) -> None:
        payload = {
            "channels": [
                channel.model_dump(mode="json")
                for channel in sort_channels(channels if channels is not None else list(self._channels.values()))
            ],
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    async def list(self) -> list[Channel]:
        async with self._lock:
            return sort_channels(list(self._channels.values()))

    async def summary(self) -> tuple[list[Channel], int, int, datetime | None]:
        channels = await self.list()
        live, offline = live_counts(channels)
        return channels, live, offline, self.last_refresh

    async def get(self, channel_id: str) -> Channel | None:
        async with self._lock:
            channel = self._channels.get(channel_id)
            return channel.model_copy(deep=True) if channel else None

    async def find_identity(self, platform: str, username: str) -> Channel | None:
        key = (platform, username.lower())
        async with self._lock:
            for channel in self._channels.values():
                if channel.identity_key() == key:
                    return channel.model_copy(deep=True)
        return None

    def _existing_source(self, key: tuple[str, str]) -> Channel | None:
        return next((item for item in self._channels.values() if item.source_key() == key), None)

    def _channel_from_resolved(
        self,
        resolved: ResolvedChannel,
        snapshot: ChannelSnapshot,
        *,
        existing: Channel | None = None,
        added_at=None,
    ) -> Channel:
        channel = existing.model_copy(deep=True) if existing else Channel(
            platform=resolved.platform,
            username=resolved.username,
            added_at=added_at or utcnow(),
        )
        channel.platform = resolved.platform
        channel.username = resolved.username
        channel.channel_id = snapshot.channel_id or resolved.channel_id
        channel.stream_id = snapshot.stream_id
        channel.display_name = snapshot.display_name or resolved.display_name
        channel.url = snapshot.url or resolved.url
        channel.live = snapshot.live
        channel.viewers = snapshot.viewers if snapshot.live else 0
        channel.title = snapshot.title
        channel.game = snapshot.game
        channel.thumbnail = snapshot.thumbnail
        channel.last_checked = utcnow()
        channel.last_error = ""
        return channel

    async def add(self, channel: Channel) -> Channel:
        async with self._lock:
            existing = self._existing_source(channel.source_key())
            if existing:
                raise ValueError(
                    f"{channel.display_name or channel.username} is already on the master list"
                )
            self._channels[channel.id] = channel
            self.last_refresh = utcnow()
            self._write_unlocked()
            return channel.model_copy(deep=True)

    async def add_from_resolved(self, resolved: ResolvedChannel) -> Channel:
        async with self._lock:
            if self._existing_source(resolved.source_key()):
                raise ValueError(
                    f"{resolved.display_name or resolved.username} is already on the master list"
                )
            created: list[Channel] = []
            for snapshot in resolved.display_snapshots():
                channel = self._channel_from_resolved(resolved, snapshot)
                self._channels[channel.id] = channel
                created.append(channel)
            self.last_refresh = utcnow()
            self._write_unlocked()
            return sort_channels(created)[0].model_copy(deep=True)

    async def remove(self, channel_id: str) -> list[str]:
        async with self._lock:
            channel = self._channels.get(channel_id)
            if channel is None:
                return []
            removed = [item.id for item in self._channels.values() if item.source_key() == channel.source_key()]
            for item_id in removed:
                del self._channels[item_id]
            self._write_unlocked()
            return removed

    async def replace_source_streams(self, template: Channel, resolved: ResolvedChannel) -> list[Channel]:
        async with self._lock:
            updated = self._replace_source_streams_locked(template, resolved)
            self._write_unlocked()
            return updated

    def _replace_source_streams_locked(self, template: Channel, resolved: ResolvedChannel) -> list[Channel]:
        """Caller must hold self._lock and write afterwards."""
        existing = [item for item in self._channels.values() if item.source_key() == template.source_key()]
        if not existing:
            return []
        by_stream = {item.stream_id: item for item in existing}
        added_at = min(item.added_at for item in existing)
        keep_ids: set[str] = set()
        updated: list[Channel] = []
        for snapshot in resolved.display_snapshots():
            prior = by_stream.get(snapshot.stream_id)
            channel = self._channel_from_resolved(
                resolved,
                snapshot,
                existing=prior,
                added_at=added_at,
            )
            self._channels[channel.id] = channel
            keep_ids.add(channel.id)
            updated.append(channel)
        for item in existing:
            if item.id not in keep_ids:
                del self._channels[item.id]
        self.last_refresh = utcnow()
        return [item.model_copy(deep=True) for item in sort_channels(updated)]

    async def apply_snapshot(self, channel_id: str, snapshot: ChannelSnapshot, error: str = "") -> Channel | None:
        async with self._lock:
            channel = self._channels.get(channel_id)
            if channel is None:
                return None
            channel.live = snapshot.live
            channel.viewers = snapshot.viewers if snapshot.live else 0
            if snapshot.title:
                channel.title = snapshot.title
            if snapshot.game:
                channel.game = snapshot.game
            if snapshot.thumbnail:
                channel.thumbnail = snapshot.thumbnail
            if snapshot.display_name:
                channel.display_name = snapshot.display_name
            if snapshot.channel_id:
                channel.channel_id = snapshot.channel_id
            if snapshot.stream_id:
                channel.stream_id = snapshot.stream_id
            if snapshot.url:
                channel.url = snapshot.url
            if not snapshot.live:
                channel.title = snapshot.title
                channel.game = snapshot.game
            channel.last_checked = utcnow()
            channel.last_error = error
            self.last_refresh = channel.last_checked
            self._write_unlocked()
            return channel.model_copy(deep=True)

    async def mark_error(self, channel_id: str, error: str) -> None:
        async with self._lock:
            self._mark_error_locked(channel_id, error)
            self._write_unlocked()

    def _mark_error_locked(self, channel_id: str, error: str) -> None:
        """Caller must hold self._lock and write afterwards."""
        channel = self._channels.get(channel_id)
        if channel is None:
            return
        channel.last_checked = utcnow()
        channel.last_error = error
        self.last_refresh = channel.last_checked

    @asynccontextmanager
    async def batch(self):
        """Hold the lock across several *_locked mutations, writing to disk once at the end."""
        async with self._lock:
            yield
            self._write_unlocked()
