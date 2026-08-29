"""Primary resolver: yt-dlp as a library (DESIGN.md 1)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..errors import NoMedia, classify
from ..models import MediaItem, Tweet, Variant
from ..urls import TweetRef


def _variants(formats) -> tuple[Variant, ...]:
    out: list[Variant] = []
    for f in formats or []:
        url = f.get("url")
        if not url or f.get("vcodec") == "none":   # skip audio-only renditions
            continue
        proto = f.get("protocol") or ""
        tbr = f.get("tbr")
        out.append(Variant(
            url=url,
            kind="hls" if "m3u8" in proto else "mp4",
            width=f.get("width"),
            height=f.get("height"),
            bitrate=int(tbr * 1000) if tbr else None,
        ))
    return tuple(out)


def _is_gif(entry: dict) -> bool:
    """X serves animated GIFs as silent looping MP4s (DESIGN.md 2)."""
    formats = entry.get("formats") or []
    if any("/tweet_video/" in (f.get("url") or "") for f in formats):
        return True
    if formats and all(f.get("acodec") in ("none", None) for f in formats):
        return True
    return False


def _entries(info: dict) -> list[dict]:
    """A tweet with several videos comes back as a playlist."""
    if info.get("_type") == "playlist":
        return [e for e in (info.get("entries") or []) if e]
    return [info]


def to_tweet(info: dict, ref: TweetRef) -> Tweet:
    """Map a yt-dlp info dict onto our model. Pure — unit-testable offline."""
    entries = _entries(info)
    media = tuple(
        MediaItem(
            index=i,
            kind="animated_gif" if _is_gif(e) else "video",
            duration_s=e.get("duration"),
            variants=_variants(e.get("formats")),
            source_url=e.get("webpage_url") or ref.canonical_url,
        )
        for i, e in enumerate(entries)
        if e.get("formats") or e.get("url")
    )
    head = entries[0] if entries else {}
    ts = head.get("timestamp") or info.get("timestamp")
    author = (head.get("uploader_id") or info.get("uploader_id")
              or ref.author or "unknown").lstrip("@")
    return Tweet(
        id=ref.id,
        author=author,
        url=ref.canonical_url,
        text=(head.get("description") or info.get("description") or "").strip(),
        created_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
        media=media,
    )


class _CaptureLogger:
    """yt-dlp writes errors through its own logger even when quiet=True.

    Without this it prints ERROR lines straight to stderr and the message is
    reported twice — once by yt-dlp, once by our handler.
    """

    def __init__(self):
        self.errors: list[str] = []

    def debug(self, msg): pass

    def info(self, msg): pass

    def warning(self, msg): pass

    def error(self, msg):
        self.errors.append(str(msg))


class YtDlpResolver:
    name = "yt-dlp"

    def __init__(self, cookies_from_browser: str | None = None, quiet: bool = True):
        self.cookies_from_browser = cookies_from_browser
        self.quiet = quiet

    def base_opts(self) -> dict:
        opts: dict = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": True,
            "logger": _CaptureLogger(),
        }
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        return opts

    def resolve(self, ref: TweetRef) -> Tweet:
        import yt_dlp

        opts = self.base_opts() | {"skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ref.canonical_url, download=False)
        except Exception as exc:
            raise classify(str(exc)) from exc

        if not info:
            raise NoMedia(f"nothing resolvable at {ref.canonical_url}")
        tweet = to_tweet(info, ref)
        if not tweet.has_media:
            raise NoMedia(
                f"no video or GIF found — the tweet may contain only photos, "
                f"or may not exist: {ref.canonical_url}")
        return tweet
