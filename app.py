from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from liveplayer.config import Settings, settings as default_settings
from liveplayer.models import (
    Channel,
    ChannelCreate,
    ChannelListResponse,
    ChannelSearchQuery,
    ChannelSearchResponse,
    PlayResponse,
)
from liveplayer.parsing import ChannelInputError, parse_channel_input
from liveplayer.platforms.base import ChannelLookupError
from liveplayer.platforms.registry import PlatformRegistry, default_clients
from liveplayer.player import PlayerError, StreamPlayer
from liveplayer.poller import StreamPoller
from liveplayer.store import ChannelStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("live-player")


def create_app(
    settings: Settings | None = None,
    registry: PlatformRegistry | None = None,
    player: StreamPlayer | None = None,
) -> FastAPI:
    config = settings or default_settings
    store = ChannelStore(config.data_file)
    http = httpx.AsyncClient(timeout=20.0, follow_redirects=True)
    platforms = registry or PlatformRegistry(default_clients(http, config))
    poller = StreamPoller(store, platforms, config.poll_seconds)
    stream_player = player or StreamPlayer(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.load()
        app.state.store = store
        app.state.platforms = platforms
        app.state.poller = poller
        app.state.player = stream_player
        app.state.http = http
        app.state.settings = config
        if config.poll_seconds > 0:
            poller.start()
        yield
        await poller.stop()
        await stream_player.stop_all()
        await http.aclose()

    app = FastAPI(title="Live Player", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/channels", response_model=ChannelListResponse)
    async def list_channels():
        channels, live_count, offline_count, last_refresh = await store.summary()
        return ChannelListResponse(
            channels=channels,
            live_count=live_count,
            offline_count=offline_count,
            last_refresh=last_refresh,
        )

    @app.post("/api/channels/search", response_model=ChannelSearchResponse)
    async def search_channels(payload: ChannelSearchQuery):
        try:
            query = payload.query.strip()
            if not query:
                raise ChannelInputError("Search text is required")
            results = await platforms.search(payload.platform, query)
        except ChannelInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ChannelLookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not search {payload.platform}: {exc}") from exc
        return ChannelSearchResponse(query=payload.query, platform=payload.platform, results=results)

    @app.post("/api/channels", response_model=Channel)
    async def add_channel(payload: ChannelCreate):
        try:
            lookup = _add_lookup(payload)
            resolved = await platforms.resolve(payload.platform, lookup)
        except ChannelInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ChannelLookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach {payload.platform}: {exc}") from exc

        try:
            saved = await store.add_from_resolved(resolved)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return saved

    @app.delete("/api/channels/{channel_id}")
    async def remove_channel(channel_id: str):
        removed = await store.remove(channel_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Channel not found")
        for item_id in removed:
            await stream_player.stop(item_id)
        return {"ok": True}

    @app.post("/api/channels/refresh")
    async def refresh_all():
        await poller.refresh_all()
        return await list_channels()

    @app.post("/api/channels/{channel_id}/play", response_model=PlayResponse)
    async def play_channel(channel_id: str):
        channel = await store.get(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        if not channel.live:
            raise HTTPException(status_code=409, detail=f"{channel.display_name} is offline")
        try:
            session = await stream_player.play(channel)
        except PlayerError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return PlayResponse(
            channel_id=channel.id,
            display_name=session.display_name,
            stream_url=stream_player.public_stream_url(session.port),
            playlist_url=stream_player.public_playlist_url(channel.id),
            vlc_url=stream_player.vlc_launch_url(channel.id),
            port=session.port,
        )

    @app.get("/api/channels/{channel_id}/stream")
    async def play_stream(channel_id: str):
        channel = await store.get(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        if not channel.live:
            raise HTTPException(status_code=409, detail=f"{channel.display_name} is offline")
        try:
            session = await stream_player.play(channel)
        except PlayerError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return RedirectResponse(stream_player.public_stream_url(session.port), status_code=302)

    @app.get("/api/channels/{channel_id}/play.m3u")
    async def play_playlist(channel_id: str):
        channel = await store.get(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        session = stream_player.get(channel_id)
        if session is None:
            if not channel.live:
                raise HTTPException(status_code=409, detail=f"{channel.display_name} is offline")
            session = await stream_player.play(channel)
        filename = f"{session.display_name}.m3u".replace(" ", "_")
        return PlainTextResponse(
            stream_player.playlist_body(session),
            media_type="audio/x-mpegurl",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/")
    async def index():
        return FileResponse("static/index.html")

    return app


def _add_lookup(payload: ChannelCreate) -> str:
    """YouTube is keyed by channel id; Twitch/Kick lookups use the login/slug."""
    if payload.platform == "youtube" and payload.channel_id:
        return payload.channel_id
    if payload.username:
        return parse_channel_input(payload.platform, payload.username)
    if payload.channel_id:
        return payload.channel_id
    raise ChannelInputError("Username is required")


app = create_app()
