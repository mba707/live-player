from __future__ import annotations

from typing import Protocol

from liveplayer.models import Channel, ChannelCandidate, Platform, ResolvedChannel


class ChannelLookupError(LookupError):
    pass


class PlatformClient(Protocol):
    platform: Platform

    async def resolve(self, username: str) -> ResolvedChannel:
        """Verify a channel exists and return current live metadata."""

    async def search(self, query: str) -> list[ChannelCandidate]:
        """Return matching accounts so the user can pick the exact one."""

    async def refresh(self, channels: list[Channel]) -> dict[str, ResolvedChannel]:
        """Refresh live state for channels on this platform, keyed by store id."""
