from __future__ import annotations

import asyncio

from liveplayer.models import Channel, ChannelCandidate, Platform, ResolvedChannel
from liveplayer.platforms.base import ChannelLookupError, PlatformClient
from liveplayer.platforms.kick import KickClient
from liveplayer.platforms.twitch import TwitchClient
from liveplayer.platforms.youtube import YoutubeClient


class PlatformRegistry:
    def __init__(self, clients: dict[Platform, PlatformClient]):
        self.clients = clients

    def get(self, platform: Platform) -> PlatformClient:
        try:
            return self.clients[platform]
        except KeyError as exc:
            raise ChannelLookupError(f"No client registered for {platform}") from exc

    async def resolve(self, platform: Platform, username: str) -> ResolvedChannel:
        return await self.get(platform).resolve(username)

    async def search(self, platform: Platform, query: str) -> list[ChannelCandidate]:
        return await self.get(platform).search(query)

    async def refresh(self, channels: list[Channel]) -> dict[str, ResolvedChannel | Exception]:
        grouped: dict[Platform, list[Channel]] = {}
        for channel in channels:
            grouped.setdefault(channel.platform, []).append(channel)

        group_results = await asyncio.gather(
            *(self._refresh_group(platform, group) for platform, group in grouped.items())
        )
        results: dict[str, ResolvedChannel | Exception] = {}
        for group_result in group_results:
            results.update(group_result)
        return results

    async def _refresh_group(
        self, platform: Platform, group: list[Channel]
    ) -> dict[str, ResolvedChannel | Exception]:
        client = self.get(platform)
        try:
            return await client.refresh(group)
        except Exception:  # noqa: BLE001 - fall back to per-channel resolves, keep other platforms polling
            outcomes = await asyncio.gather(
                *(client.resolve(channel.username) for channel in group),
                return_exceptions=True,
            )
            return {channel.id: outcome for channel, outcome in zip(group, outcomes)}


def default_clients(http, settings) -> dict[Platform, PlatformClient]:
    return {
        "twitch": TwitchClient(http, settings.twitch_client_id, settings.twitch_client_secret),
        "youtube": YoutubeClient(http, settings.youtube_api_key),
        "kick": KickClient(http),
    }
