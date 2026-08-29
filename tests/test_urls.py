import pytest
from birdnest.urls import NotATweetURL, TweetRef, parse, parse_many

ID = "1234567890123456789"


@pytest.mark.parametrize("raw", [
    f"https://x.com/jack/status/{ID}",
    f"https://twitter.com/jack/status/{ID}",
    f"https://mobile.twitter.com/jack/status/{ID}",
    f"https://www.x.com/jack/status/{ID}?s=20&t=abc",
    f"x.com/jack/status/{ID}",                      # no scheme
    f"  https://x.com/jack/status/{ID}  ",          # padding
    f"<https://x.com/jack/status/{ID}>",            # chat-client angle brackets
    f"https://vxtwitter.com/jack/status/{ID}",      # embed-fixer mirrors
    f"https://fxtwitter.com/jack/status/{ID}",
    f"https://x.com/jack/statuses/{ID}",            # legacy plural
])
def test_parses_author_and_id(raw):
    ref = parse(raw)
    assert ref.id == ID
    assert ref.author == "jack"


def test_bare_id():
    assert parse(ID) == TweetRef(id=ID)


def test_media_index_from_photo_video_suffix():
    assert parse(f"https://x.com/jack/status/{ID}/video/2").media_index == 2
    assert parse(f"https://x.com/jack/status/{ID}/photo/1").media_index == 1
    assert parse(f"https://x.com/jack/status/{ID}").media_index is None


def test_anonymous_i_web_form_has_no_author():
    for raw in (f"https://x.com/i/web/status/{ID}", f"https://x.com/i/status/{ID}"):
        assert parse(raw).author is None


def test_canonical_url_normalises_host_and_drops_tracking():
    ref = parse(f"https://mobile.twitter.com/jack/status/{ID}?s=20")
    assert ref.canonical_url == f"https://x.com/jack/status/{ID}"
    assert parse(ID).canonical_url == f"https://x.com/i/status/{ID}"


@pytest.mark.parametrize("raw", [
    "", "   ", "https://example.com/jack/status/123",
    "https://x.com/jack", "https://x.com/jack/status/notanumber",
    "https://youtube.com/watch?v=abc",
])
def test_rejects_non_tweets(raw):
    with pytest.raises(NotATweetURL):
        parse(raw)


def test_parse_many_skips_blanks_and_dedupes():
    refs = parse_many([
        f"https://x.com/jack/status/{ID}", "", "# a comment",
        f"https://twitter.com/jack/status/{ID}?s=9",   # same tweet, other form
        "9876543210",
    ])
    assert [r.id for r in refs] == [ID, "9876543210"]
