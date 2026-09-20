from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    data_file: Path
    public_host: str
    public_port: int
    listen_host: str
    listen_port: int
    poll_seconds: int
    stream_port_start: int
    stream_port_end: int
    twitch_client_id: str
    twitch_client_secret: str
    youtube_api_key: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_file=Path(os.environ.get("DATA_FILE", "data/livestreams.json")),
            public_host=os.environ.get("PUBLIC_HOST", "127.0.0.1"),
            public_port=_int("PUBLIC_PORT", 8112),
            listen_host=os.environ.get("LISTEN_HOST", "0.0.0.0"),
            listen_port=_int("LISTEN_PORT", 8112),
            poll_seconds=_int("POLL_SECONDS", 60),
            stream_port_start=_int("STREAM_PORT_START", 8888),
            stream_port_end=_int("STREAM_PORT_END", 8897),
            twitch_client_id=os.environ.get("TWITCH_CLIENT_ID", ""),
            twitch_client_secret=os.environ.get("TWITCH_CLIENT_SECRET", ""),
            youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        )


settings = Settings.from_env()
