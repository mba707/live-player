from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from urllib.parse import quote

from liveplayer.config import Settings
from liveplayer.models import Channel

logger = logging.getLogger(__name__)


class PlayerError(RuntimeError):
    pass


@dataclass
class PlaySession:
    channel_id: str
    display_name: str
    url: str
    port: int
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)


class StreamPlayer:
    """Start streamlink's HTTP endpoint so VLC can open a LAN playlist."""

    def __init__(self, settings: Settings, streamlink_bin: str | None = None):
        self.settings = settings
        self.streamlink_bin = streamlink_bin or shutil.which("streamlink") or "streamlink"
        self._sessions: dict[str, PlaySession] = {}
        self._lock = asyncio.Lock()

    def playlist_body(self, session: PlaySession) -> str:
        stream_url = self.public_stream_url(session.port)
        return (
            "#EXTM3U\n"
            f"#EXTINF:-1,{session.display_name}\n"
            f"{stream_url}\n"
        )

    def public_stream_url(self, port: int) -> str:
        return f"http://{self.settings.public_host}:{port}/"

    def public_playlist_url(self, channel_id: str) -> str:
        return (
            f"http://{self.settings.public_host}:{self.settings.public_port}"
            f"/api/channels/{channel_id}/play.m3u"
        )

    def public_stream_proxy_url(self, channel_id: str) -> str:
        return (
            f"http://{self.settings.public_host}:{self.settings.public_port}"
            f"/api/channels/{channel_id}/stream"
        )

    def vlc_url(self, port: int) -> str:
        return self.vlc_open_url(self.public_stream_url(port))

    def vlc_launch_url(self, channel_id: str) -> str:
        return self.vlc_open_url(self.public_stream_proxy_url(channel_id))

    def vlc_open_url(self, stream_url: str) -> str:
        """Chrome mangles vlc://http://… into vlc://http//… so use a query URL instead."""
        return f"liveplayer:?url={quote(stream_url, safe='')}"

    async def play(self, channel: Channel) -> PlaySession:
        if not channel.url:
            raise PlayerError("Channel has no stream URL")
        async with self._lock:
            existing = self._sessions.get(channel.id)
            if existing and existing.process and existing.process.returncode is None:
                return existing
            port = self._allocate_port()
            process = await self._spawn(channel.url, port)
            session = PlaySession(
                channel_id=channel.id,
                display_name=channel.title or channel.display_name or channel.username,
                url=channel.url,
                port=port,
                process=process,
            )
            self._sessions[channel.id] = session
            await self._wait_for_port(process, port)
            return session

    async def stop(self, channel_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(channel_id, None)
        if session and session.process and session.process.returncode is None:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=5)
            except TimeoutError:
                session.process.kill()

    async def stop_all(self) -> None:
        async with self._lock:
            ids = list(self._sessions)
        for channel_id in ids:
            await self.stop(channel_id)

    def get(self, channel_id: str) -> PlaySession | None:
        return self._sessions.get(channel_id)

    def _allocate_port(self) -> int:
        used = {session.port for session in self._sessions.values()}
        for port in range(self.settings.stream_port_start, self.settings.stream_port_end + 1):
            if port not in used:
                return port
        raise PlayerError("All VLC stream ports are in use")

    async def _spawn(self, url: str, port: int) -> asyncio.subprocess.Process:
        command = [
            self.streamlink_bin,
            "--player-external-http",
            "--player-external-http-port",
            str(port),
            "--player-external-http-interface",
            "0.0.0.0",
            url,
            "best",
        ]
        logger.info("Launching streamlink for %s on port %s", url, port)
        try:
            return await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise PlayerError("streamlink is not installed in the container") from exc

    async def _wait_for_port(self, process: asyncio.subprocess.Process | None, port: int) -> None:
        if process is None:
            return
        for _ in range(40):
            if process.returncode is not None:
                raise PlayerError("streamlink exited before VLC could connect")
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                await asyncio.sleep(0.25)
        raise PlayerError("streamlink started but the VLC port never opened")
