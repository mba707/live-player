from __future__ import annotations

import asyncio
from typing import Any

import httpx

from liveplayer.models import Channel, ChannelSnapshot, ResolvedChannel, candidate_from_resolved

from .base import ChannelLookupError

KICK_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}


class KickClient:
    platform = "kick"

    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def resolve(self, username: str) -> ResolvedChannel:
        slug = username.lower()
        response = await self.http.get(
            f"https://kick.com/api/v2/channels/{slug}",
            headers=KICK_HEADERS,
        )
        if response.status_code == 404:
            raise ChannelLookupError(f"Kick channel {slug!r} was not found")
        response.raise_for_status()
        return self._from_payload(slug, response.json())

    async def search(self, query: str) -> list[ChannelCandidate]:
        resolved = await self.resolve(query)
        return [candidate_from_resolved(resolved)]

    async def refresh(self, channels: list[Channel]) -> dict[str, ResolvedChannel]:
        resolved = await asyncio.gather(*(self.resolve(channel.username) for channel in channels))
        return {channel.id: result for channel, result in zip(channels, resolved)}

    def _from_payload(self, slug: str, payload: dict[str, Any]) -> ResolvedChannel:
        user = payload.get("user") or {}
        livestream = payload.get("livestream") or None
        login = (payload.get("slug") or user.get("username") or slug).lower()
        display = user.get("username") or payload.get("slug") or login
        url = f"https://kick.com/{login}"
        category = ""
        if livestream:
            categories = livestream.get("categories") or []
            if categories:
                category = categories[0].get("name") or categories[0].get("slug") or ""
            category = category or livestream.get("category_name") or ""
        snapshot = ChannelSnapshot(
            live=bool(livestream and (livestream.get("is_live") or livestream.get("id"))),
            viewers=int((livestream or {}).get("viewer_count") or 0),
            title=(livestream or {}).get("session_title") or (livestream or {}).get("title") or "",
            game=category,
            thumbnail=_kick_thumb(livestream, payload),
            display_name=display,
            channel_id=str(payload.get("id") or user.get("id") or ""),
            url=url,
        )
        return ResolvedChannel(
            platform="kick",
            username=login,
            channel_id=snapshot.channel_id,
            display_name=snapshot.display_name,
            url=url,
            snapshot=snapshot,
        )


def _kick_thumb(livestream: dict[str, Any] | None, payload: dict[str, Any]) -> str:
    raw = (livestream or {}).get("thumbnail") or payload.get("banner_image") or ""
    if isinstance(raw, dict):
        return str(raw.get("src") or raw.get("url") or "")
    return str(raw or "")
