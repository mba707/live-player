from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Platform = Literal["youtube", "twitch", "kick"]
PLATFORMS: tuple[Platform, ...] = ("youtube", "twitch", "kick")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Channel(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    platform: Platform
    username: str
    channel_id: str = ""
    stream_id: str = ""
    display_name: str = ""
    url: str = ""
    live: bool = False
    viewers: int = 0
    title: str = ""
    game: str = ""
    thumbnail: str = ""
    added_at: datetime = Field(default_factory=utcnow)
    last_checked: datetime | None = None
    last_error: str = ""

    def source_key(self) -> tuple[str, str]:
        """The followed account. YouTube can expand this into several live rows."""
        if self.channel_id:
            return self.platform, self.channel_id.lower()
        return self.platform, self.username.lower()

    def identity_key(self) -> tuple[str, str]:
        return self.source_key()


class ChannelCreate(BaseModel):
    platform: Platform
    username: str
    channel_id: str = ""


class ChannelSearchQuery(BaseModel):
    platform: Platform
    query: str


class ChannelCandidate(BaseModel):
    platform: Platform
    username: str
    channel_id: str
    display_name: str
    url: str
    thumbnail: str = ""
    description: str = ""
    subscribers: str = ""


class ChannelSearchResponse(BaseModel):
    query: str
    platform: Platform
    results: list[ChannelCandidate]


def candidate_from_resolved(resolved: ResolvedChannel, **overrides) -> ChannelCandidate:
    data = {
        "platform": resolved.platform,
        "username": resolved.username,
        "channel_id": resolved.channel_id,
        "display_name": resolved.display_name,
        "url": resolved.url,
        "thumbnail": resolved.snapshot.thumbnail,
    }
    data.update(overrides)
    return ChannelCandidate(**data)


class ChannelSnapshot(BaseModel):
    live: bool = False
    viewers: int = 0
    title: str = ""
    game: str = ""
    thumbnail: str = ""
    display_name: str = ""
    channel_id: str = ""
    stream_id: str = ""
    url: str = ""


class ResolvedChannel(BaseModel):
    platform: Platform
    username: str
    channel_id: str
    display_name: str
    url: str
    snapshot: ChannelSnapshot = Field(default_factory=ChannelSnapshot)
    streams: list[ChannelSnapshot] = Field(default_factory=list)

    def source_key(self) -> tuple[str, str]:
        if self.channel_id:
            return self.platform, self.channel_id.lower()
        return self.platform, self.username.lower()

    def display_snapshots(self) -> list[ChannelSnapshot]:
        """One snapshot per live video, or a single offline placeholder."""
        lives = [item for item in self.streams if item.live]
        if lives:
            return lives
        if self.snapshot.live:
            return [self.snapshot]
        return [
            ChannelSnapshot(
                live=False,
                viewers=0,
                title="",
                display_name=self.snapshot.display_name or self.display_name,
                channel_id=self.channel_id or self.snapshot.channel_id,
                stream_id="",
                url=self.url or self.snapshot.url,
            )
        ]


class ChannelListResponse(BaseModel):
    channels: list[Channel]
    live_count: int
    offline_count: int
    last_refresh: datetime | None = None


class PlayResponse(BaseModel):
    channel_id: str
    display_name: str
    stream_url: str
    playlist_url: str
    vlc_url: str
    port: int
