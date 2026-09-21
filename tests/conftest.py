from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app import create_app
from liveplayer.config import Settings
from liveplayer.models import Channel, ChannelCandidate, ChannelSnapshot, ResolvedChannel, candidate_from_resolved
from liveplayer.platforms.base import ChannelLookupError
from liveplayer.platforms.registry import PlatformRegistry
from liveplayer.player import PlaySession, StreamPlayer


def _compact(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


class FakeClient:
    def __init__(
        self,
        platform: str,
        catalog: dict[str, ResolvedChannel] | None = None,
        extra_search: list[ChannelCandidate] | None = None,
    ):
        self.platform = platform
        self.catalog = catalog or {}
        self.extra_search = extra_search or []
        self.calls: list[str] = []

    async def resolve(self, username: str) -> ResolvedChannel:
        self.calls.append(username)
        key = username.lower().lstrip("@")
        if key in self.catalog:
            return self.catalog[key]
        for resolved in self.catalog.values():
            if resolved.channel_id.lower() == username.lower() or resolved.username.lower().lstrip("@") == key:
                return resolved
        raise ChannelLookupError(f"{self.platform} user {username!r} was not found")

    async def search(self, query: str) -> list[ChannelCandidate]:
        needle = _compact(query)
        matches = [
            candidate_from_resolved(resolved)
            for key, resolved in self.catalog.items()
            if needle in _compact(key) or needle in _compact(resolved.display_name)
        ]
        seen = {item.channel_id for item in matches}
        for item in self.extra_search:
            if item.channel_id not in seen and (
                needle in _compact(item.display_name) or needle in _compact(item.username)
            ):
                matches.append(item)
        if not matches:
            raise ChannelLookupError(f"{self.platform} user {query!r} was not found")
        return matches

    async def refresh(self, channels: list[Channel]) -> dict[str, ResolvedChannel]:
        return {channel.id: await self.resolve(channel.username) for channel in channels}


class FakePlayer(StreamPlayer):
    def __init__(self, settings: Settings):
        super().__init__(settings, streamlink_bin="streamlink")
        self.started: list[str] = []

    async def _spawn(self, url: str, port: int):
        self.started.append(url)
        return None

    async def play(self, channel: Channel) -> PlaySession:
        if not channel.url:
            raise RuntimeError("Channel has no stream URL")
        session = PlaySession(
            channel_id=channel.id,
            display_name=channel.display_name or channel.username,
            url=channel.url,
            port=self.settings.stream_port_start,
            process=None,
        )
        self._sessions[channel.id] = session
        self.started.append(channel.url)
        return session


def make_resolved(
    platform: str,
    username: str,
    *,
    live: bool = False,
    viewers: int = 0,
    display_name: str | None = None,
    streams: list[ChannelSnapshot] | None = None,
) -> ResolvedChannel:
    handle = username.lower().lstrip("@")
    url = {
        "twitch": f"https://www.twitch.tv/{handle}",
        "kick": f"https://kick.com/{handle}",
        "youtube": f"https://www.youtube.com/@{handle}",
    }[platform]
    display = display_name or username
    snapshot = ChannelSnapshot(
        live=live,
        viewers=viewers,
        title="Live now" if live else "",
        game="Just Chatting" if live else "",
        display_name=display,
        channel_id=f"{platform}-{handle}",
        url=url,
    )
    live_streams = streams
    if live_streams is None:
        live_streams = [snapshot] if live else []
    return ResolvedChannel(
        platform=platform,  # type: ignore[arg-type]
        username=username if platform == "youtube" else handle,
        channel_id=snapshot.channel_id or (live_streams[0].channel_id if live_streams else ""),
        display_name=display,
        url=url,
        snapshot=live_streams[0] if live_streams else snapshot,
        streams=live_streams,
    )


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(
        data_file=tmp_path / "livestreams.json",
        public_host="localhost",
        public_port=8112,
        listen_host="0.0.0.0",
        listen_port=8112,
        poll_seconds=0,
        stream_port_start=8888,
        stream_port_end=8897,
        twitch_client_id="",
        twitch_client_secret="",
        youtube_api_key="",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake_registry():
    return PlatformRegistry(
        {
            "twitch": FakeClient(
                "twitch",
                {
                    "shroud": make_resolved("twitch", "shroud", live=True, viewers=12345, display_name="shroud"),
                    "lirik": make_resolved("twitch", "lirik", live=False, display_name="LIRIK"),
                },
            ),
            "youtube": FakeClient(
                "youtube",
                {
                    "mrbeast": make_resolved("youtube", "@MrBeast", live=True, viewers=88000, display_name="MrBeast"),
                    "informationzulu": make_resolved(
                        "youtube", "@InformationZulu", display_name="Information Zulu"
                    ),
                    "infozulu": make_resolved("youtube", "@infozulu", display_name="Information Zulu"),
                    "nasaspaceflight": make_resolved(
                        "youtube",
                        "@NASASpaceflight",
                        display_name="NASASpaceflight",
                        streams=[
                            ChannelSnapshot(
                                live=True,
                                viewers=1200,
                                title="Starbase Live",
                                display_name="NASASpaceflight",
                                channel_id="youtube-nasaspaceflight",
                                stream_id="mhJRzQsLZGg",
                                url="https://www.youtube.com/watch?v=mhJRzQsLZGg",
                            ),
                            ChannelSnapshot(
                                live=True,
                                viewers=348,
                                title="Space Coast Live",
                                display_name="NASASpaceflight",
                                channel_id="youtube-nasaspaceflight",
                                stream_id="Jm8wRjD3xVA",
                                url="https://www.youtube.com/watch?v=Jm8wRjD3xVA",
                            ),
                            ChannelSnapshot(
                                live=True,
                                viewers=18,
                                title="McGregor Live",
                                display_name="NASASpaceflight",
                                channel_id="youtube-nasaspaceflight",
                                stream_id="cOmmvhDQ2HM",
                                url="https://www.youtube.com/watch?v=cOmmvhDQ2HM",
                            ),
                        ],
                    ),
                },
            ),
            "kick": FakeClient(
                "kick",
                {
                    "xqc": make_resolved("kick", "xqc", live=True, viewers=21000, display_name="xQc"),
                },
            ),
        }
    )


@pytest.fixture
async def api_client(tmp_path, fake_registry):
    settings = make_settings(tmp_path)
    player = FakePlayer(settings)
    app = create_app(settings=settings, registry=fake_registry, player=player)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app
        client.player = player
        yield client
