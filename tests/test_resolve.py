import json
from pathlib import Path

import pytest
from birdnest.resolve.ytdlp import to_tweet
from birdnest.urls import parse

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def test_single_video_maps_metadata():
    ref = parse("https://x.com/jack/status/1700000000000000001")
    t = to_tweet(load("single_video"), ref)
    assert t.author == "jack"            # leading @ stripped
    assert t.id == "1700000000000000001"
    assert t.text == "a tweet with a video"
    assert t.created_at.year == 2025
    assert len(t.media) == 1
    assert t.media[0].kind == "video"


def test_best_prefers_highest_progressive_mp4_over_hls():
    ref = parse("https://x.com/jack/status/1700000000000000001")
    best = to_tweet(load("single_video"), ref).media[0].best
    assert best.kind == "mp4"            # not the 1080p m3u8
    assert (best.width, best.height) == (1280, 720)


def test_audio_only_renditions_are_not_variants():
    ref = parse("https://x.com/jack/status/1700000000000000001")
    urls = [v.url for v in to_tweet(load("single_video"), ref).media[0].variants]
    assert not any(".m4a" in u for u in urls)
    assert len(urls) == 3


def test_animated_gif_detected_from_tweet_video_url():
    ref = parse("https://x.com/someone/status/1700000000000000002")
    item = to_tweet(load("animated_gif"), ref).media[0]
    assert item.kind == "animated_gif"
    assert item.is_gif


def test_playlist_becomes_indexed_media_with_per_item_kinds():
    ref = parse("https://x.com/multi/status/1700000000000000003")
    t = to_tweet(load("multi_video"), ref)
    assert [m.index for m in t.media] == [0, 1]
    assert [m.kind for m in t.media] == ["video", "animated_gif"]
    assert t.author == "multi"


def test_tweet_with_no_formats_has_no_media():
    ref = parse("https://x.com/jack/status/1700000000000000001")
    assert not to_tweet({"id": "x", "uploader_id": "@jack"}, ref).has_media


def test_author_falls_back_to_url_when_payload_lacks_it():
    ref = parse("https://x.com/fromurl/status/1700000000000000001")
    assert to_tweet({"formats": [{"url": "u", "protocol": "https"}]}, ref).author == "fromurl"
