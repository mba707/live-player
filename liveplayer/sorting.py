from __future__ import annotations

from liveplayer.models import Channel


def sort_channels(channels: list[Channel]) -> list[Channel]:
    """Live channels first, then viewer count, then name. Offline stay visible."""
    return sorted(
        channels,
        key=lambda channel: (
            0 if channel.live else 1,
            -channel.viewers if channel.live else 0,
            (channel.display_name or channel.username).lower(),
            (channel.title or "").lower(),
        ),
    )


def live_counts(channels: list[Channel]) -> tuple[int, int]:
    live = sum(1 for channel in channels if channel.live)
    return live, len(channels) - live
