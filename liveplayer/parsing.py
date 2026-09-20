from __future__ import annotations

from urllib.parse import urlparse

from liveplayer.models import PLATFORMS, Platform


class ChannelInputError(ValueError):
    pass


def normalize_platform(value: str) -> Platform:
    platform = (value or "").strip().lower()
    if platform not in PLATFORMS:
        raise ChannelInputError(f"Unsupported platform: {value!r}")
    return platform  # type: ignore[return-value]


def parse_channel_input(platform: str, raw: str) -> str:
    """Turn a username or pasted URL into the stored channel handle."""
    normalized_platform = normalize_platform(platform)
    text = (raw or "").strip()
    if not text:
        raise ChannelInputError("Username is required")

    if "://" in text or text.startswith("www."):
        text = _from_url(normalized_platform, text)

    text = text.strip().strip("/")
    if not text:
        raise ChannelInputError("Could not read a username from that input")

    if normalized_platform == "youtube":
        return _youtube_handle(text)
    return text.lstrip("@").lower()


def _from_url(platform: Platform, raw: str) -> str:
    url = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]

    expected = {
        "youtube": ("youtube.com", "youtu.be", "m.youtube.com"),
        "twitch": ("twitch.tv", "m.twitch.tv"),
        "kick": ("kick.com",),
    }[platform]
    if host and host not in expected:
        raise ChannelInputError(f"{raw!r} is not a {platform} URL")

    if platform == "youtube":
        if host == "youtu.be" and parts:
            raise ChannelInputError("Paste a channel URL or @handle, not a video link")
        if len(parts) >= 2 and parts[0] in {"channel", "c", "user", "handle"}:
            return parts[1]
        if parts and parts[0].startswith("@"):
            return parts[0]
        if parts:
            return parts[0]
        raise ChannelInputError("Could not find a YouTube channel in that URL")

    if not parts:
        raise ChannelInputError(f"Could not find a {platform} username in that URL")
    return parts[0]


def _youtube_handle(text: str) -> str:
    if text.startswith("UC") and len(text) >= 24:
        return text
    handle = text if text.startswith("@") else f"@{text}"
    return handle
