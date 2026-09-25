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


def test_liveplayer_opener_uses_macos_open_and_linux_vlc(tmp_path, monkeypatch):
    opener = runpy.run_path(str(OPENER))
    assert opener["vlc_command"]("darwin") == ["open", "-a", "VLC"]
    vlc = tmp_path / "VideoLAN" / "VLC" / "vlc.exe"
    vlc.parent.mkdir(parents=True)
    vlc.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert opener["vlc_command"]("win32") == [str(vlc)]
