from liveplayer.models import Channel, ChannelSnapshot, ResolvedChannel
from liveplayer.store import ChannelStore


async def test_store_round_trip_and_duplicate_rejection(tmp_path):
    store = ChannelStore(tmp_path / "livestreams.json")
    store.load()

    first = await store.add(Channel(platform="twitch", username="shroud", display_name="shroud"))
    assert first.id
    listed = await store.list()
    assert listed[0].username == "shroud"

    store_again = ChannelStore(tmp_path / "livestreams.json")
    store_again.load()
    assert (await store_again.list())[0].username == "shroud"

    try:
        await store.add(Channel(platform="twitch", username="Shroud", display_name="Shroud"))
        raise AssertionError("duplicate should have been rejected")
    except ValueError as exc:
        assert "already on the master list" in str(exc)


async def test_apply_snapshot_clears_viewers_when_offline(tmp_path):
    store = ChannelStore(tmp_path / "livestreams.json")
    store.load()
    channel = await store.add(
        Channel(platform="twitch", username="lirik", display_name="LIRIK", live=True, viewers=50)
    )

    updated = await store.apply_snapshot(channel.id, ChannelSnapshot(live=False, viewers=50, title=""))
    assert updated is not None
    assert updated.live is False
    assert updated.viewers == 0


def _nsf(streams: list[ChannelSnapshot]) -> ResolvedChannel:
    return ResolvedChannel(
        platform="youtube",
        username="@NASASpaceflight",
        channel_id="UCSUu1lih2RifWkKtDOJdsBA",
        display_name="NASASpaceflight",
        url="https://www.youtube.com/channel/UCSUu1lih2RifWkKtDOJdsBA",
        snapshot=streams[0] if streams else ChannelSnapshot(display_name="NASASpaceflight"),
        streams=streams,
    )


async def test_add_from_resolved_expands_youtube_lives(tmp_path):
    store = ChannelStore(tmp_path / "livestreams.json")
    store.load()
    first = await store.add_from_resolved(
        _nsf(
            [
                ChannelSnapshot(
                    live=True,
                    viewers=1200,
                    title="Starbase Live",
                    display_name="NASASpaceflight",
                    channel_id="UCSUu1lih2RifWkKtDOJdsBA",
                    stream_id="mhJRzQsLZGg",
                    url="https://www.youtube.com/watch?v=mhJRzQsLZGg",
                ),
                ChannelSnapshot(
                    live=True,
                    viewers=348,
                    title="Space Coast Live",
                    display_name="NASASpaceflight",
                    channel_id="UCSUu1lih2RifWkKtDOJdsBA",
                    stream_id="Jm8wRjD3xVA",
                    url="https://www.youtube.com/watch?v=Jm8wRjD3xVA",
                ),
            ]
        )
    )
    listed = await store.list()
    assert first.title == "Starbase Live"
    assert [item.title for item in listed] == ["Starbase Live", "Space Coast Live"]
    assert all(item.live for item in listed)

    try:
        await store.add_from_resolved(_nsf([]))
        raise AssertionError("duplicate channel should have been rejected")
    except ValueError as exc:
        assert "already on the master list" in str(exc)


async def test_replace_source_streams_keeps_ids_and_collapses_offline(tmp_path):
    store = ChannelStore(tmp_path / "livestreams.json")
    store.load()
    starbase = ChannelSnapshot(
        live=True,
        viewers=900,
        title="Starbase Live",
        display_name="NASASpaceflight",
        channel_id="UCSUu1lih2RifWkKtDOJdsBA",
        stream_id="mhJRzQsLZGg",
        url="https://www.youtube.com/watch?v=mhJRzQsLZGg",
    )
    coast = ChannelSnapshot(
        live=True,
        viewers=100,
        title="Space Coast Live",
        display_name="NASASpaceflight",
        channel_id="UCSUu1lih2RifWkKtDOJdsBA",
        stream_id="Jm8wRjD3xVA",
        url="https://www.youtube.com/watch?v=Jm8wRjD3xVA",
    )
    await store.add_from_resolved(_nsf([starbase, coast]))
    before = {item.stream_id: item.id for item in await store.list()}

    starbase.viewers = 1500
    updated = await store.replace_source_streams((await store.list())[0], _nsf([starbase]))
    assert [item.stream_id for item in updated] == ["mhJRzQsLZGg"]
    assert updated[0].id == before["mhJRzQsLZGg"]
    assert updated[0].viewers == 1500
    assert len(await store.list()) == 1

    offline = await store.replace_source_streams(updated[0], _nsf([]))
    assert len(offline) == 1
    assert offline[0].live is False
    assert offline[0].viewers == 0
    assert offline[0].stream_id == ""


async def test_remove_deletes_every_stream_for_that_channel(tmp_path):
    store = ChannelStore(tmp_path / "livestreams.json")
    store.load()
    await store.add(Channel(platform="twitch", username="shroud", display_name="shroud"))
    added = await store.add_from_resolved(
        _nsf(
            [
                ChannelSnapshot(
                    live=True,
                    viewers=10,
                    title="One",
                    channel_id="UCSUu1lih2RifWkKtDOJdsBA",
                    stream_id="aaaaaaaaaaa",
                    display_name="NASASpaceflight",
                ),
                ChannelSnapshot(
                    live=True,
                    viewers=5,
                    title="Two",
                    channel_id="UCSUu1lih2RifWkKtDOJdsBA",
                    stream_id="bbbbbbbbbbb",
                    display_name="NASASpaceflight",
                ),
            ]
        )
    )
    removed = await store.remove(added.id)
    assert len(removed) == 2
    leftover = await store.list()
    assert [item.username for item in leftover] == ["shroud"]
