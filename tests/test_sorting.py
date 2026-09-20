from liveplayer.models import Channel
from liveplayer.sorting import live_counts, sort_channels


def test_live_channels_sort_above_offline_by_viewers():
    channels = [
        Channel(platform="twitch", username="offline-one", display_name="Zed", live=False, viewers=0),
        Channel(platform="twitch", username="small-live", display_name="Ada", live=True, viewers=12),
        Channel(platform="kick", username="big-live", display_name="Bea", live=True, viewers=9000),
        Channel(platform="youtube", username="@quiet", display_name="Cara", live=False, viewers=0),
    ]

    ordered = [channel.username for channel in sort_channels(channels)]

    assert ordered == ["big-live", "small-live", "@quiet", "offline-one"]
    assert live_counts(channels) == (2, 2)


def test_offline_channels_remain_on_the_list():
    channels = [
        Channel(platform="twitch", username="gone", display_name="Gone", live=False),
        Channel(platform="twitch", username="live", display_name="Live", live=True, viewers=3),
    ]
    ordered = sort_channels(channels)
    assert [channel.live for channel in ordered] == [True, False]
    assert {channel.username for channel in ordered} == {"gone", "live"}
