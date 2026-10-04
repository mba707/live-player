import json

import httpx
import pytest
import respx

from liveplayer.platforms.base import ChannelLookupError
from liveplayer.platforms.kick import KickClient
from liveplayer.platforms.twitch import TwitchClient
from liveplayer.platforms.youtube import YoutubeClient, parse_watching_count, parse_youtube_live_videos


@respx.mock
async def test_twitch_gql_live_and_missing():
    respx.post("https://gql.twitch.tv/gql").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "id": "1",
                            "login": "shroud",
                            "displayName": "shroud",
                            "stream": {
                                "title": "Valorant",
                                "viewersCount": 14000,
                                "game": {"name": "VALORANT"},
                            },
                        }
                    }
                },
            ),
            httpx.Response(200, json={"data": {"user": None}}),
        ]
    )
    async with httpx.AsyncClient() as http:
        client = TwitchClient(http)
        live = await client.resolve("shroud")
        assert live.snapshot.live is True
        assert live.snapshot.viewers == 14000
        with pytest.raises(ChannelLookupError):
            await client.resolve("missing")


@respx.mock
async def test_twitch_resolves_numeric_user_id():
    respx.post("https://gql.twitch.tv/gql").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "id": "260261471",
                        "login": "asmongold",
                        "displayName": "Asmongold",
                        "stream": None,
                    }
                }
            },
        )
    )
    async with httpx.AsyncClient() as http:
        resolved = await TwitchClient(http).resolve("260261471")
    assert resolved.username == "asmongold"
    assert resolved.channel_id == "260261471"


@respx.mock
async def test_kick_channel_payload():
    respx.get("https://kick.com/api/v2/channels/xqc").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 99,
                "slug": "xqc",
                "user": {"username": "xQc"},
                "livestream": {
                    "id": 1,
                    "is_live": True,
                    "viewer_count": 21000,
                    "session_title": "Just chatting",
                    "categories": [{"name": "Just Chatting"}],
                    "thumbnail": {"src": "https://img/kick.jpg"},
                },
            },
        )
    )
    async with httpx.AsyncClient() as http:
        resolved = await KickClient(http).resolve("xQc")
    assert resolved.display_name == "xQc"
    assert resolved.snapshot.live is True
    assert resolved.snapshot.viewers == 21000
    assert resolved.snapshot.thumbnail == "https://img/kick.jpg"


@respx.mock
async def test_youtube_parses_channel_page():
    html = """
    <link rel="canonical" href="https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA">
    <meta property="og:title" content="MrBeast">
    <script>var ytInitialPlayerResponse = %s;</script>
    """ % json.dumps(
        {
            "videoDetails": {
                "title": "Live stream",
                "isLive": True,
                "videoId": "abcdefghijk",
            }
        }
    )
    html += '"isLiveNow":true "text":"12,345 watching" "videoId":"abcdefghijk"'
    respx.get(url__startswith="https://www.youtube.com/").mock(return_value=httpx.Response(200, text=html))
    respx.post("https://www.youtube.com/youtubei/v1/browse?prettyPrint=false").mock(
        return_value=httpx.Response(200, json={})
    )

    async with httpx.AsyncClient() as http:
        resolved = await YoutubeClient(http).resolve("MrBeast")
    assert resolved.channel_id == "UCX6OQ3DkcsbYNE6H8uQQuVA"
    assert resolved.snapshot.live is True
    assert resolved.snapshot.viewers == 12345
    assert resolved.snapshot.stream_id == "abcdefghijk"
    assert resolved.snapshot.url == "https://www.youtube.com/watch?v=abcdefghijk"


@respx.mock
async def test_youtube_resolve_expands_browse_lives():
    html = """
    <link rel="canonical" href="https://www.youtube.com/channel/UCSUu1lih2RifWkKtDOJdsBA">
    <meta property="og:title" content="NASASpaceflight">
    """
    respx.get(url__startswith="https://www.youtube.com/").mock(return_value=httpx.Response(200, text=html))
    respx.post("https://www.youtube.com/youtubei/v1/browse?prettyPrint=false").mock(
        return_value=httpx.Response(
            200,
            json={
                "contents": [
                    {
                        "lockupViewModel": {
                            "contentId": "mhJRzQsLZGg",
                            "contentImage": {
                                "thumbnailViewModel": {
                                    "overlays": [
                                        {
                                            "thumbnailBottomOverlayViewModel": {
                                                "badges": [{"thumbnailBadgeViewModel": {"text": "LIVE"}}]
                                            }
                                        }
                                    ]
                                }
                            },
                            "metadata": {
                                "lockupMetadataViewModel": {
                                    "title": {"content": "Starbase Live"},
                                    "metadata": {
                                        "contentMetadataViewModel": {
                                            "metadataRows": [
                                                {"metadataParts": [{"text": {"content": "1.2K watching"}}]}
                                            ]
                                        }
                                    },
                                }
                            },
                        }
                    },
                    {
                        "lockupViewModel": {
                            "contentId": "Jm8wRjD3xVA",
                            "contentImage": {
                                "thumbnailViewModel": {
                                    "overlays": [
                                        {
                                            "thumbnailBottomOverlayViewModel": {
                                                "badges": [{"thumbnailBadgeViewModel": {"text": "LIVE"}}]
                                            }
                                        }
                                    ]
                                }
                            },
                            "metadata": {
                                "lockupMetadataViewModel": {
                                    "title": {"content": "Space Coast Live"},
                                    "metadata": {
                                        "contentMetadataViewModel": {
                                            "metadataRows": [
                                                {"metadataParts": [{"text": {"content": "348 watching"}}]}
                                            ]
                                        }
                                    },
                                }
                            },
                        }
                    },
                ]
            },
        )
    )

    async with httpx.AsyncClient() as http:
        resolved = await YoutubeClient(http).resolve("NASASpaceflight")
    assert [item.stream_id for item in resolved.streams] == ["mhJRzQsLZGg", "Jm8wRjD3xVA"]
    assert [item.viewers for item in resolved.streams] == [1200, 348]
    assert resolved.snapshot.title == "Starbase Live"


def test_parse_watching_count_accepts_compact_suffixes():
    assert parse_watching_count("348 watching") == 348
    assert parse_watching_count("1.2K watching") == 1200
    assert parse_watching_count('"text":"12,345 watching"') == 12345


def test_parse_youtube_live_videos_from_lockups():
    payload = {
        "contents": {
            "richItemRenderer": {
                "content": {
                    "lockupViewModel": {
                        "contentId": "mhJRzQsLZGg",
                        "contentImage": {
                            "thumbnailViewModel": {
                                "overlays": [
                                    {
                                        "thumbnailBottomOverlayViewModel": {
                                            "badges": [{"thumbnailBadgeViewModel": {"text": "LIVE"}}]
                                        }
                                    }
                                ]
                            }
                        },
                        "metadata": {
                            "lockupMetadataViewModel": {
                                "title": {"content": "Starbase Live"},
                                "metadata": {
                                    "contentMetadataViewModel": {
                                        "metadataRows": [
                                            {"metadataParts": [{"text": {"content": "1.2K watching"}}]}
                                        ]
                                    }
                                },
                            }
                        },
                    }
                }
            }
        }
    }
    upcoming = {
        "lockupViewModel": {
            "contentId": "upcomingxxxx",
            "metadata": {"lockupMetadataViewModel": {"title": {"content": "Later"}}},
            "contentImage": {
                "thumbnailViewModel": {
                    "overlays": [
                        {
                            "thumbnailBottomOverlayViewModel": {
                                "badges": [{"thumbnailBadgeViewModel": {"text": "Upcoming"}}]
                            }
                        }
                    ]
                }
            },
        }
    }
    payload["extra"] = upcoming
    lives = parse_youtube_live_videos(payload, channel_id="UCNSF", display_name="NASASpaceflight")
    assert len(lives) == 1
    assert lives[0].stream_id == "mhJRzQsLZGg"
    assert lives[0].title == "Starbase Live"
    assert lives[0].viewers == 1200
    assert lives[0].url == "https://www.youtube.com/watch?v=mhJRzQsLZGg"


@respx.mock
async def test_youtube_scheduled_stream_is_not_live():
    html = (
        '<link rel="canonical" href="https://www.youtube.com/channel/UCkQef3Fidr7tm3gNuXgGKPw">'
        '<meta property="og:title" content="BIG JET TV">'
        '"playabilityStatus":{"status":"LIVE_STREAM_OFFLINE","reason":"This live event will begin in 25 minutes."}'
        '"isLive":true "isUpcoming":true "isLiveNow":false "text":"LIVE" "videoId":"Tp49a8I5zYE"'
    )
    respx.get(url__startswith="https://www.youtube.com/").mock(return_value=httpx.Response(200, text=html))
    respx.post("https://www.youtube.com/youtubei/v1/browse?prettyPrint=false").mock(
        return_value=httpx.Response(200, json={})
    )
    async with httpx.AsyncClient() as http:
        resolved = await YoutubeClient(http).resolve("UCkQef3Fidr7tm3gNuXgGKPw")
    assert resolved.snapshot.live is False
    assert resolved.streams == []


def test_parse_youtube_skips_upcoming_videos_in_browse_results():
    payload = {
        "contents": [
            {
                "videoRenderer": {
                    "videoId": "Tp49a8I5zYE",
                    "title": {"runs": [{"text": "Scheduled"}]},
                    "thumbnailOverlays": [
                        {"thumbnailOverlayTimeStatusRenderer": {"style": "LIVE"}}
                    ],
                    "upcomingEventData": {"startTime": "1800000000"},
                }
            }
        ]
    }
    assert parse_youtube_live_videos(payload, channel_id="UCkQef3Fidr7tm3gNuXgGKPw") == []
