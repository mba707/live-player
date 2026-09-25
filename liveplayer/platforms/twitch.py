from __future__ import annotations

import asyncio
from typing import Any

import httpx

from liveplayer.models import Channel, ChannelSnapshot, ResolvedChannel, candidate_from_resolved

from .base import ChannelLookupError

TWITCH_WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
USER_FIELDS = """
    id
    login
    displayName
    profileImageURL(width: 70)
    stream {
      id
      title
      viewersCount
      createdAt
      game { name }
      previewImageURL(width: 440, height: 248)
    }
"""
USER_BY_LOGIN_QUERY = f"""
query($login: String!) {{
  user(login: $login) {{
    {USER_FIELDS}
  }}
}}
"""
USER_BY_ID_QUERY = f"""
query($id: ID!) {{
  user(id: $id) {{
    {USER_FIELDS}
  }}
}}
"""


class TwitchClient:
    platform = "twitch"

    def __init__(
        self,
        http: httpx.AsyncClient,
        client_id: str = "",
        client_secret: str = "",
    ):
        self.http = http
        self.client_id = client_id
        self.client_secret = client_secret
        self._app_token: str = ""

    async def resolve(self, username: str) -> ResolvedChannel:
        identifier = username.strip()
        if self.client_id and self.client_secret:
            return await self._resolve_helix(identifier)
        return await self._resolve_gql(identifier)

    async def search(self, query: str) -> list[ChannelCandidate]:
        resolved = await self.resolve(query)
        return [candidate_from_resolved(resolved)]

    async def refresh(self, channels: list[Channel]) -> dict[str, ResolvedChannel]:
        resolved = await asyncio.gather(*(self.resolve(channel.username) for channel in channels))
        return {channel.id: result for channel, result in zip(channels, resolved)}

    async def _resolve_gql(self, identifier: str) -> ResolvedChannel:
        if identifier.isdigit():
            query = USER_BY_ID_QUERY
            variables = {"id": identifier}
        else:
            query = USER_BY_LOGIN_QUERY
            variables = {"login": identifier.lower()}
        response = await self.http.post(
            "https://gql.twitch.tv/gql",
            headers={
                "Client-ID": TWITCH_WEB_CLIENT_ID,
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()
        user = ((payload.get("data") or {}).get("user")) if isinstance(payload, dict) else None
        if not user:
            raise ChannelLookupError(f"Twitch user {identifier!r} was not found")
        return self._from_gql_user(user)

    async def _resolve_helix(self, identifier: str) -> ResolvedChannel:
        token = await self._app_token_value()
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
        }
        params = {"id": identifier} if identifier.isdigit() else {"login": identifier.lower()}
        user_resp = await self.http.get(
            "https://api.twitch.tv/helix/users",
            params=params,
            headers=headers,
        )
        user_resp.raise_for_status()
        users = user_resp.json().get("data") or []
        if not users:
            raise ChannelLookupError(f"Twitch user {identifier!r} was not found")
        user = users[0]
        stream_resp = await self.http.get(
            "https://api.twitch.tv/helix/streams",
            params={"user_id": user["id"]},
            headers=headers,
        )
        stream_resp.raise_for_status()
        streams = stream_resp.json().get("data") or []
        stream = streams[0] if streams else None
        login = user.get("login") or identifier
        url = f"https://www.twitch.tv/{login}"
        snapshot = ChannelSnapshot(
            live=bool(stream),
            viewers=int(stream.get("viewer_count", 0)) if stream else 0,
            title=stream.get("title", "") if stream else "",
            game=stream.get("game_name", "") if stream else "",
            thumbnail=_twitch_thumb(stream.get("thumbnail_url")) if stream else user.get("profile_image_url", ""),
            display_name=user.get("display_name") or login,
            channel_id=str(user.get("id") or ""),
            url=url,
        )
        return ResolvedChannel(
            platform="twitch",
            username=user.get("login") or login,
            channel_id=snapshot.channel_id,
            display_name=snapshot.display_name,
            url=url,
            snapshot=snapshot,
        )

    async def _app_token_value(self) -> str:
        if self._app_token:
            return self._app_token
        response = await self.http.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        self._app_token = response.json()["access_token"]
        return self._app_token

    def _from_gql_user(self, user: dict[str, Any]) -> ResolvedChannel:
        login = user.get("login") or ""
        if not login:
            raise ChannelLookupError("Twitch user was not found")
        stream = user.get("stream") or None
        url = f"https://www.twitch.tv/{login}"
        snapshot = ChannelSnapshot(
            live=bool(stream),
            viewers=int((stream or {}).get("viewersCount") or 0),
            title=(stream or {}).get("title") or "",
            game=((stream or {}).get("game") or {}).get("name") or "",
            thumbnail=(stream or {}).get("previewImageURL") or user.get("profileImageURL") or "",
            display_name=user.get("displayName") or login,
            channel_id=str(user.get("id") or ""),
            url=url,
        )
        return ResolvedChannel(
            platform="twitch",
            username=login,
            channel_id=snapshot.channel_id,
            display_name=snapshot.display_name,
            url=url,
            snapshot=snapshot,
        )


def _twitch_thumb(template: str | None) -> str:
    if not template:
        return ""
    return template.replace("{width}", "440").replace("{height}", "248")
