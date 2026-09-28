import runpy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from liveplayer.models import Channel
from liveplayer.player import StreamPlayer
from tests.conftest import make_settings


OPENER = Path(__file__).resolve().parents[1] / "static" / "live-player-open"


def test_playlist_points_at_lan_vlc_url(tmp_path):
    settings = make_settings(tmp_path)
    player = StreamPlayer(settings)
    channel = Channel(
        id="abc123",
        platform="twitch",
        username="shroud",
        display_name="shroud",
        url="https://www.twitch.tv/shroud",
        live=True,
    )
    session = player._sessions.setdefault(
        channel.id,
        type("S", (), {"channel_id": channel.id, "display_name": "shroud", "url": channel.url, "port": 8888, "process": None})(),
    )

    body = player.playlist_body(session)
    assert body.splitlines()[0] == "#EXTM3U"
    assert "http://localhost:8888/" in body
    assert player.vlc_url(8888) == "liveplayer:?url=http%3A%2F%2Flocalhost%3A8888%2F"
    assert player.vlc_launch_url("abc123") == (
        "liveplayer:?url=http%3A%2F%2Flocalhost%3A8112%2Fapi%2Fchannels%2Fabc123%2Fstream"
    )
    parsed = urlparse(player.vlc_launch_url("abc123"))
    assert parsed.scheme == "liveplayer"
    assert parsed.netloc == ""
    assert parse_qs(parsed.query)["url"] == [
        "http://localhost:8112/api/channels/abc123/stream"
    ]
    assert player.public_playlist_url("abc123").endswith("/api/channels/abc123/play.m3u")


def test_liveplayer_opener_reads_stream_url():
    opener = runpy.run_path(str(OPENER))
    raw = "liveplayer:?url=http%3A%2F%2Flocalhost%3A8888%2F"
    assert opener["stream_url"](raw) == "http://localhost:8888/"
    try:
        opener["stream_url"]("liveplayer:?url=file:///etc/passwd")
        raise AssertionError("file URLs must be rejected")
    except ValueError as exc:
        assert "refused" in str(exc)


def test_liveplayer_opener_uses_macos_open_and_linux_vlc():
    opener = runpy.run_path(str(OPENER))
    assert opener["vlc_command"]("darwin") == ["open", "-a", "VLC"]


def test_play_keeps_only_two_streams_and_drops_the_oldest(tmp_path):
    import asyncio

    settings = make_settings(tmp_path)
    assert settings.stream_max_sessions == 2

    class Proc:
        def __init__(self):
            self.returncode = None

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    class Player(StreamPlayer):
        async def _spawn(self, url, port):
            return Proc()

        async def _wait_for_port(self, process, port):
            return None

    async def scenario():
        player = Player(settings)
        channels = [
            Channel(id=f"c{i}", platform="twitch", username=f"u{i}", url=f"https://twitch.tv/u{i}", live=True)
            for i in range(3)
        ]
        first = await player.play(channels[0])
        second = await player.play(channels[1])
        third = await player.play(channels[2])
        return player, first, second, third

    player, first, second, third = asyncio.run(scenario())
    assert list(player._sessions) == ["c1", "c2"]
    assert first.process.returncode == -15
    assert second.process.returncode is None
    assert third.port == first.port
