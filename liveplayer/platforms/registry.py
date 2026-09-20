from __future__ import annotations

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

        results: dict[str, ResolvedChannel | Exception] = {}
        for platform, group in grouped.items():
            client = self.get(platform)
            try:
                resolved = await client.refresh(group)
                results.update(resolved)
            except Exception as exc:  # noqa: BLE001 - keep other platforms polling
                for channel in group:
                    try:
                        results[channel.id] = await client.resolve(channel.username)
                    except Exception as inner:  # noqa: BLE001
                        results[channel.id] = inner
                if not any(channel.id in results for channel in group):
                    for channel in group:
                        results[channel.id] = exc
        return results


def default_clients(http, settings) -> dict[Platform, PlatformClient]:
    return {
        "twitch": TwitchClient(http, settings.twitch_client_id, settings.twitch_client_secret),
        "youtube": YoutubeClient(http, settings.youtube_api_key),
        "kick": KickClient(http),
    }
