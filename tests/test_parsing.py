import pytest

from liveplayer.parsing import ChannelInputError, parse_channel_input


@pytest.mark.parametrize(
    ("platform", "raw", "expected"),
    [
        ("twitch", "Shroud", "shroud"),
        ("twitch", "https://www.twitch.tv/shroud", "shroud"),
        ("twitch", "https://twitch.tv/shroud/videos", "shroud"),
        ("kick", "xQc", "xqc"),
        ("kick", "https://kick.com/xqc", "xqc"),
        ("youtube", "MrBeast", "@MrBeast"),
        ("youtube", "@MrBeast", "@MrBeast"),
        ("youtube", "https://www.youtube.com/@MrBeast", "@MrBeast"),
        ("youtube", "https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA", "UCX6OQ3DkcsbYNE6H8uQQuVA"),
    ],
)
def test_parse_channel_input(platform, raw, expected):
    assert parse_channel_input(platform, raw) == expected


def test_rejects_empty_username():
    with pytest.raises(ChannelInputError):
        parse_channel_input("twitch", "  ")


def test_rejects_unknown_platform():
    with pytest.raises(ChannelInputError):
        parse_channel_input("mixer", "someone")


def test_rejects_mismatched_url():
    with pytest.raises(ChannelInputError):
        parse_channel_input("twitch", "https://kick.com/xqc")
