from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from liveplayer.models import Channel, ChannelCandidate, ChannelSnapshot, ResolvedChannel, candidate_from_resolved

from .base import ChannelLookupError

logger = logging.getLogger(__name__)

CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[\w-]{20,})"')
CANONICAL_RE = re.compile(
    r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{20,})"'
)
TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]+)"')
LIVE_BADGE_RE = re.compile(r'"isLiveNow"\s*:\s*true|"isLive":true')
VIDEO_ID_RE = re.compile(r'"videoId":"([\w-]{11})"')
VIDEO_ID_TOKEN_RE = re.compile(r"^[\w-]{11}$")
WATCHING_RE = re.compile(r"([\d,.]+)\s*([kKmMbB])?\s+watching", re.I)
STREAMS_BROWSE_PARAMS = "EgdzdHJlYW1z8gYECgJ6AA=="
YOUTUBE_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}


class YoutubeClient:
    platform = "youtube"

    def __init__(self, http: httpx.AsyncClient, api_key: str = ""):
        self.http = http
        self.api_key = api_key

    async def resolve(self, username: str) -> ResolvedChannel:
        handle = username
        page_url = self._page_url(handle)
        html = await self._get_html(page_url)
        channel_id = self._extract_channel_id(html)
        if not channel_id:
            raise ChannelLookupError(f"YouTube channel {handle!r} was not found")
        title_match = TITLE_RE.search(html)
        display = _unescape(title_match.group(1) if title_match else handle)
        clean_display = display.removesuffix(" - YouTube").strip() or handle
        channel_url = f"https://www.youtube.com/channel/{channel_id}"
        streams = await self._list_live_videos(channel_id, clean_display)
        snapshot = streams[0] if streams else ChannelSnapshot(
            live=False,
            display_name=clean_display,
            channel_id=channel_id,
            url=channel_url,
        )
        if not streams:
            live_html = html
            if "/live" not in page_url:
                try:
                    live_html = await self._get_html(f"{channel_url}/live")
                except httpx.HTTPError:
                    live_html = html
            snapshot = self._snapshot_from_html(
                handle=handle,
                channel_id=channel_id,
                display=clean_display,
                html=live_html,
            )
            if snapshot.live:
                streams = [snapshot]
        return ResolvedChannel(
            platform="youtube",
            username=handle,
            channel_id=channel_id,
            display_name=clean_display,
            url=channel_url,
            snapshot=snapshot,
            streams=streams,
        )

    async def search(self, query: str) -> list[ChannelCandidate]:
        text = (query or "").strip()
        if not text:
            raise ChannelLookupError("Search text is required")
        if self._is_exact_channel(text):
            resolved = await self.resolve(text)
            return [candidate_from_resolved(resolved)]

        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240901.00.00",
                    "hl": "en",
                    "gl": "US",
                }
            },
            "query": text,
            "params": "EgIQAg==",
        }
        response = await self.http.post(
            "https://www.youtube.com/youtubei/v1/search?prettyPrint=false",
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
            },
            json=payload,
        )
        response.raise_for_status()
        results = parse_youtube_channel_results(response.json())
        if not results:
            raise ChannelLookupError(f"No YouTube channels matched {text!r}")
        return results

    def _is_exact_channel(self, text: str) -> bool:
        lowered = text.lower()
        return (text.startswith("UC") and len(text) >= 24) or "youtube.com/channel/" in lowered

    async def refresh(self, channels: list[Channel]) -> dict[str, ResolvedChannel]:
        keys = {channel.channel_id or channel.username for channel in channels}
        resolved = await asyncio.gather(*(self.resolve(key) for key in keys))
        cache = dict(zip(keys, resolved))
        return {channel.id: cache[channel.channel_id or channel.username] for channel in channels}

    async def _list_live_videos(self, channel_id: str, display: str) -> list[ChannelSnapshot]:
        payload = await self._browse_streams(channel_id)
        lives = parse_youtube_live_videos(payload, channel_id=channel_id, display_name=display)
        if lives:
            return lives
        try:
            html = await self._get_html(f"https://www.youtube.com/channel/{channel_id}/streams")
        except (ChannelLookupError, httpx.HTTPError) as exc:
            logger.info("YouTube streams page failed for %s: %s", channel_id, exc)
            return []
        return parse_youtube_live_videos(
            _extract_yt_initial_data(html),
            channel_id=channel_id,
            display_name=display,
        )

    async def _browse_streams(self, channel_id: str) -> dict[str, Any]:
        try:
            response = await self.http.post(
                "https://www.youtube.com/youtubei/v1/browse?prettyPrint=false",
                headers={**YOUTUBE_HEADERS, "Content-Type": "application/json"},
                json={
                    "context": {
                        "client": {
                            "clientName": "WEB",
                            "clientVersion": "2.20240901.00.00",
                            "hl": "en",
                            "gl": "US",
                        }
                    },
                    "browseId": channel_id,
                    "params": STREAMS_BROWSE_PARAMS,
                },
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 - scrape fallback should always continue
            logger.info("YouTube streams browse failed for %s: %s", channel_id, exc)
            return {}

    def _page_url(self, handle: str) -> str:
        if handle.startswith("UC") and len(handle) >= 24:
            return f"https://www.youtube.com/channel/{handle}"
        normalized = handle if handle.startswith("@") else f"@{handle}"
        return f"https://www.youtube.com/{normalized}"

    async def _get_html(self, url: str) -> str:
        response = await self.http.get(url, headers=YOUTUBE_HEADERS, follow_redirects=True)
        if response.status_code == 404:
            raise ChannelLookupError(f"YouTube page {url} was not found")
        response.raise_for_status()
        return response.text

    def _extract_channel_id(self, html: str) -> str:
        for pattern in (CANONICAL_RE, CHANNEL_ID_RE):
            match = pattern.search(html)
            if match:
                return match.group(1)
        return ""

    def _snapshot_from_html(
        self,
        handle: str,
        channel_id: str,
        display: str,
        html: str,
    ) -> ChannelSnapshot:
        live = bool(LIVE_BADGE_RE.search(html))
        viewers = parse_watching_count(html) if live else 0
        title = ""
        video_id = ""
        if live:
            initial = _extract_initial(html)
            title = _live_title(initial) or display
            details = initial.get("videoDetails") or {}
            video_id = str(details.get("videoId") or "")
            if not video_id:
                match = VIDEO_ID_RE.search(html)
                video_id = match.group(1) if match else ""
        clean_display = display.removesuffix(" - YouTube").strip() or handle
        url = (
            f"https://www.youtube.com/watch?v={video_id}"
            if video_id
            else f"https://www.youtube.com/channel/{channel_id}"
        )
        return ChannelSnapshot(
            live=live,
            viewers=viewers if live else 0,
            title=title if live else "",
            game="",
            thumbnail=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if live and video_id else "",
            display_name=clean_display,
            channel_id=channel_id,
            stream_id=video_id,
            url=url,
        )


def parse_watching_count(text: str) -> int:
    match = WATCHING_RE.search(text or "")
    if not match:
        return 0
    number = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").upper()
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return int(number * multiplier)


def parse_youtube_live_videos(
    payload: dict[str, Any],
    *,
    channel_id: str = "",
    display_name: str = "",
) -> list[ChannelSnapshot]:
    found: dict[str, ChannelSnapshot] = {}
    for item in _walk_keys(payload, "lockupViewModel"):
        snapshot = _snapshot_from_lockup(item, channel_id=channel_id, display_name=display_name)
        if snapshot:
            found[snapshot.stream_id] = snapshot
    for item in _walk_keys(payload, "videoRenderer"):
        snapshot = _snapshot_from_video_renderer(item, channel_id=channel_id, display_name=display_name)
        if snapshot:
            found.setdefault(snapshot.stream_id, snapshot)
    for item in _walk_keys(payload, "gridVideoRenderer"):
        snapshot = _snapshot_from_video_renderer(item, channel_id=channel_id, display_name=display_name)
        if snapshot:
            found.setdefault(snapshot.stream_id, snapshot)
    return sorted(found.values(), key=lambda item: (-item.viewers, item.title.lower()))


def _walk_keys(obj: Any, key: str):
    if isinstance(obj, dict):
        if key in obj:
            yield obj[key]
        for value in obj.values():
            yield from _walk_keys(value, key)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_keys(value, key)


def _snapshot_from_lockup(
    item: dict[str, Any],
    *,
    channel_id: str,
    display_name: str,
) -> ChannelSnapshot | None:
    blob = json.dumps(item)
    if '"text": "LIVE"' not in blob and "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE" not in blob:
        return None
    video_id = _lockup_video_id(item, blob)
    if not video_id:
        return None
    metadata = (item.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = str(((metadata.get("title") or {}).get("content")) or "")
    viewers = parse_watching_count(blob)
    thumb = _first_thumb_url(item) or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return ChannelSnapshot(
        live=True,
        viewers=viewers,
        title=title,
        thumbnail=thumb,
        display_name=display_name,
        channel_id=channel_id,
        stream_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def _snapshot_from_video_renderer(
    item: dict[str, Any],
    *,
    channel_id: str,
    display_name: str,
) -> ChannelSnapshot | None:
    blob = json.dumps(item)
    if not _video_renderer_is_live(item, blob):
        return None
    video_id = str(item.get("videoId") or "")
    if not VIDEO_ID_TOKEN_RE.match(video_id):
        return None
    title = _yt_text(item.get("title"))
    viewers = parse_watching_count(_yt_text(item.get("viewCountText")) or blob)
    thumbs = ((item.get("thumbnail") or {}).get("thumbnails") or [])
    thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return ChannelSnapshot(
        live=True,
        viewers=viewers,
        title=title,
        thumbnail=thumb,
        display_name=display_name,
        channel_id=channel_id,
        stream_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def _video_renderer_is_live(item: dict[str, Any], blob: str) -> bool:
    if '"style": "LIVE"' in blob or '"text": "LIVE"' in blob or '"isLive": true' in blob:
        return True
    for overlay in item.get("thumbnailOverlays") or []:
        status = overlay.get("thumbnailOverlayTimeStatusRenderer") or {}
        if str(status.get("style") or "").upper() == "LIVE":
            return True
    return False


def _lockup_video_id(item: dict[str, Any], blob: str) -> str:
    content_id = str(item.get("contentId") or "")
    if VIDEO_ID_TOKEN_RE.match(content_id):
        return content_id
    match = re.search(r'"addedVideoId":\s*"([\w-]{11})"', blob)
    if match:
        return match.group(1)
    match = re.search(r'"videoId":\s*"([\w-]{11})"', blob)
    return match.group(1) if match else ""


def _first_thumb_url(item: dict[str, Any]) -> str:
    for source in _walk_keys(item, "sources"):
        if isinstance(source, list):
            for entry in source:
                url = str((entry or {}).get("url") or "")
                if "ytimg.com/vi/" in url:
                    return url
    return ""


def _extract_initial(html: str) -> dict[str, Any]:
    marker = "var ytInitialPlayerResponse = "
    start = html.find(marker)
    if start == -1:
        return _extract_yt_initial_data(html)
    start += len(marker)
    try:
        return json.loads(html[start : html.find(";</script>", start)])
    except json.JSONDecodeError:
        return {}


def _extract_yt_initial_data(html: str) -> dict[str, Any]:
    marker = "var ytInitialData = "
    start = html.find(marker)
    if start == -1:
        return {}
    start += len(marker)
    try:
        return json.loads(html[start : html.find(";</script>", start)])
    except json.JSONDecodeError:
        return {}


def _live_title(payload: dict[str, Any]) -> str:
    details = payload.get("videoDetails") or {}
    if details.get("title"):
        return str(details["title"])
    return ""


def parse_youtube_channel_results(payload: dict[str, Any]) -> list[ChannelCandidate]:
    found: list[ChannelCandidate] = []
    seen: set[str] = set()
    for renderer in _walk_channel_renderers(payload):
        candidate = _candidate_from_renderer(renderer)
        if not candidate or candidate.channel_id in seen:
            continue
        seen.add(candidate.channel_id)
        found.append(candidate)
    return found


def _walk_channel_renderers(obj: Any):
    if isinstance(obj, dict):
        if "channelRenderer" in obj and isinstance(obj["channelRenderer"], dict):
            yield obj["channelRenderer"]
        for value in obj.values():
            yield from _walk_channel_renderers(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_channel_renderers(value)


def _candidate_from_renderer(item: dict[str, Any]) -> ChannelCandidate | None:
    channel_id = str(item.get("channelId") or "")
    if not channel_id:
        return None
    handle = _youtube_handle_from_renderer(item)
    display = _yt_text(item.get("title")) or handle or channel_id
    subscribers = _youtube_subscribers(item)
    thumbs = ((item.get("thumbnail") or {}).get("thumbnails") or [])
    thumb = thumbs[-1].get("url") if thumbs else ""
    if thumb.startswith("//"):
        thumb = "https:" + thumb
    description = _yt_text(item.get("descriptionSnippet"))
    return ChannelCandidate(
        platform="youtube",
        username=handle or channel_id,
        channel_id=channel_id,
        display_name=display,
        url=f"https://www.youtube.com/channel/{channel_id}",
        thumbnail=thumb,
        description=description,
        subscribers=subscribers,
    )


def _youtube_handle_from_renderer(item: dict[str, Any]) -> str:
    browse = ((item.get("navigationEndpoint") or {}).get("browseEndpoint") or {})
    raw = str(browse.get("canonicalBaseUrl") or "")
    if raw.startswith("/"):
        raw = raw[1:]
    if raw.startswith("@"):
        return raw
    subscriber = _yt_text(item.get("subscriberCountText"))
    if subscriber.startswith("@"):
        return subscriber
    return ""


def _youtube_subscribers(item: dict[str, Any]) -> str:
    first = _yt_text(item.get("subscriberCountText"))
    second = _yt_text(item.get("videoCountText"))
    for value in (first, second):
        if value and "subscriber" in value.lower():
            return value
    return second or first


def _yt_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("simpleText"):
        return str(value["simpleText"])
    return "".join(str(run.get("text") or "") for run in value.get("runs") or [])


def _unescape(value: str) -> str:
    return (
        value.replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
