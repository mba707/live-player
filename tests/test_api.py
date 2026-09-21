async def test_health(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_add_twitch_youtube_and_kick_to_master_list(api_client):
    twitch = await api_client.post("/api/channels", json={"platform": "twitch", "username": "shroud"})
    youtube = await api_client.post("/api/channels", json={"platform": "youtube", "username": "MrBeast"})
    kick = await api_client.post("/api/channels", json={"platform": "kick", "username": "xqc"})

    assert twitch.status_code == 200
    assert youtube.status_code == 200
    assert kick.status_code == 200

    listing = await api_client.get("/api/channels")
    body = listing.json()
    assert body["live_count"] == 3
    assert body["offline_count"] == 0
    names = [channel["display_name"] for channel in body["channels"]]
    assert names[0] == "MrBeast"
    assert "shroud" in names
    assert "xQc" in names


async def test_unknown_channel_is_not_saved(api_client):
    response = await api_client.post("/api/channels", json={"platform": "twitch", "username": "nope"})
    assert response.status_code == 404
    listing = await api_client.get("/api/channels")
    assert listing.json()["channels"] == []


async def test_duplicate_add_returns_conflict(api_client):
    await api_client.post("/api/channels", json={"platform": "twitch", "username": "shroud"})
    again = await api_client.post("/api/channels", json={"platform": "twitch", "username": "https://twitch.tv/shroud"})
    assert again.status_code == 409


async def test_offline_channel_stays_visible(api_client):
    await api_client.post("/api/channels", json={"platform": "twitch", "username": "lirik"})
    listing = await api_client.get("/api/channels")
    body = listing.json()
    assert body["live_count"] == 0
    assert body["offline_count"] == 1
    assert body["channels"][0]["live"] is False


async def test_play_returns_vlc_playlist(api_client):
    created = await api_client.post("/api/channels", json={"platform": "twitch", "username": "shroud"})
    channel_id = created.json()["id"]

    play = await api_client.post(f"/api/channels/{channel_id}/play")
    assert play.status_code == 200
    payload = play.json()
    assert payload["stream_url"] == "http://localhost:8888/"
    assert payload["vlc_url"] == (
        f"liveplayer:?url=http%3A%2F%2Flocalhost%3A8112%2Fapi%2Fchannels%2F{channel_id}%2Fstream"
    )
    assert api_client.player.started == ["https://www.twitch.tv/shroud"]

    stream = await api_client.get(f"/api/channels/{channel_id}/stream", follow_redirects=False)
    assert stream.status_code == 302
    assert stream.headers["location"] == "http://localhost:8888/"

    playlist = await api_client.get(f"/api/channels/{channel_id}/play.m3u")
    assert playlist.status_code == 200
    assert "audio/x-mpegurl" in playlist.headers["content-type"]
    assert "attachment;" in playlist.headers.get("content-disposition", "")
    assert "http://localhost:8888/" in playlist.text


async def test_play_rejects_offline_channel(api_client):
    created = await api_client.post("/api/channels", json={"platform": "twitch", "username": "lirik"})
    play = await api_client.post(f"/api/channels/{created.json()['id']}/play")
    assert play.status_code == 409


async def test_remove_channel(api_client):
    created = await api_client.post("/api/channels", json={"platform": "kick", "username": "xqc"})
    channel_id = created.json()["id"]
    deleted = await api_client.delete(f"/api/channels/{channel_id}")
    assert deleted.status_code == 200
    listing = await api_client.get("/api/channels")
    assert listing.json()["channels"] == []


async def test_add_youtube_expands_concurrent_lives(api_client):
    created = await api_client.post(
        "/api/channels",
        json={
            "platform": "youtube",
            "username": "@NASASpaceflight",
            "channel_id": "youtube-nasaspaceflight",
        },
    )
    assert created.status_code == 200
    listing = await api_client.get("/api/channels")
    body = listing.json()
    titles = [channel["title"] for channel in body["channels"]]
    assert titles == ["Starbase Live", "Space Coast Live", "McGregor Live"]
    assert [channel["viewers"] for channel in body["channels"]] == [1200, 348, 18]
    assert body["live_count"] == 3
    assert all(channel["display_name"] == "NASASpaceflight" for channel in body["channels"])
    assert body["channels"][0]["url"] == "https://www.youtube.com/watch?v=mhJRzQsLZGg"

    again = await api_client.post(
        "/api/channels",
        json={
            "platform": "youtube",
            "username": "@NASASpaceflight",
            "channel_id": "youtube-nasaspaceflight",
        },
    )
    assert again.status_code == 409

    play = await api_client.post(f"/api/channels/{body['channels'][0]['id']}/play")
    assert play.status_code == 200
    assert api_client.player.started[-1] == "https://www.youtube.com/watch?v=mhJRzQsLZGg"

    deleted = await api_client.delete(f"/api/channels/{body['channels'][1]['id']}")
    assert deleted.status_code == 200
    leftover = await api_client.get("/api/channels")
    assert leftover.json()["channels"] == []
