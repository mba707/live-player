from liveplayer.platforms.youtube import parse_youtube_channel_results


SEARCH_PAYLOAD = {
    "contents": {
        "sectionListRenderer": {
            "contents": [
                {
                    "itemSectionRenderer": {
                        "contents": [
                            {
                                "channelRenderer": {
                                    "channelId": "UCwUOv8_NNeLaFrjtUpO-VqQ",
                                    "title": {"simpleText": "Information Zulu"},
                                    "navigationEndpoint": {
                                        "browseEndpoint": {"canonicalBaseUrl": "/@InformationZulu"}
                                    },
                                    "subscriberCountText": {"simpleText": "@InformationZulu"},
                                    "videoCountText": {"simpleText": "90.9K subscribers"},
                                    "descriptionSnippet": {
                                        "runs": [{"text": "Flight Simulator live map"}]
                                    },
                                    "thumbnail": {
                                        "thumbnails": [{"url": "//yt3.example/one.jpg"}]
                                    },
                                }
                            },
                            {
                                "channelRenderer": {
                                    "channelId": "UC7wwCzATaq9IoDkI2bdhEDA",
                                    "title": {"simpleText": "Information Zulu"},
                                    "navigationEndpoint": {
                                        "browseEndpoint": {"canonicalBaseUrl": "/@infozulu"}
                                    },
                                    "subscriberCountText": {"simpleText": "@infozulu"},
                                    "videoCountText": {"simpleText": "1.41K subscribers"},
                                    "descriptionSnippet": {
                                        "runs": [{"text": "VATSIM controller"}]
                                    },
                                    "thumbnail": {
                                        "thumbnails": [{"url": "https://yt3.example/two.jpg"}]
                                    },
                                }
                            },
                        ]
                    }
                }
            ]
        }
    }
}


def test_youtube_search_returns_multiple_accounts():
    results = parse_youtube_channel_results(SEARCH_PAYLOAD)
    assert [item.username for item in results] == ["@InformationZulu", "@infozulu"]
    assert results[0].subscribers == "90.9K subscribers"
    assert results[0].thumbnail.startswith("https://")
    assert results[1].description == "VATSIM controller"


async def test_search_endpoint_lists_youtube_matches(api_client):
    response = await api_client.post(
        "/api/channels/search",
        json={"platform": "youtube", "query": "informationzulu"},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) >= 2
    handles = {item["username"] for item in results}
    assert "@InformationZulu" in handles
    assert "@infozulu" in handles


async def test_add_uses_selected_youtube_channel(api_client):
    search = await api_client.post(
        "/api/channels/search",
        json={"platform": "youtube", "query": "informationzulu"},
    )
    chosen = next(item for item in search.json()["results"] if item["username"] == "@infozulu")
    added = await api_client.post(
        "/api/channels",
        json={
            "platform": "youtube",
            "username": chosen["username"],
            "channel_id": chosen["channel_id"],
        },
    )
    assert added.status_code == 200
    body = added.json()
    assert body["username"] == "@infozulu"
    assert body["display_name"] == "Information Zulu"


async def test_add_uses_twitch_login_not_numeric_id(api_client):
    added = await api_client.post(
        "/api/channels",
        json={
            "platform": "twitch",
            "username": "shroud",
            "channel_id": "260261471",
        },
    )
    assert added.status_code == 200
    assert added.json()["username"] == "shroud"
