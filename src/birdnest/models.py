"""Plain data passed between pipeline stages.

Deliberately free of yt-dlp types so resolution can be tested against recorded
payloads with no network (DESIGN.md 3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MediaKind = Literal["video", "animated_gif"]


@dataclass(frozen=True)
class Variant:
    url: str
    kind: Literal["mp4", "hls"]
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None

    @property
    def pixels(self) -> int:
        return (self.width or 0) * (self.height or 0)


@dataclass(frozen=True)
class MediaItem:
    index: int
    kind: MediaKind
    duration_s: float | None = None
    variants: tuple[Variant, ...] = ()
    # yt-dlp's own handle for this item; download goes through yt-dlp, not
    # through Variant.url, so HLS muxing stays its problem (DESIGN.md 5.1).
    source_url: str | None = None

    @property
    def is_gif(self) -> bool:
        return self.kind == "animated_gif"

    @property
    def best(self) -> Variant | None:
        """Highest-resolution progressive variant, falling back to HLS."""
        if not self.variants:
            return None
        mp4 = [v for v in self.variants if v.kind == "mp4"]
        pool = mp4 or list(self.variants)
        return max(pool, key=lambda v: (v.pixels, v.bitrate or 0))


@dataclass(frozen=True)
class Tweet:
    id: str
    author: str
    url: str
    text: str = ""
    created_at: datetime | None = None
    media: tuple[MediaItem, ...] = ()

    @property
    def has_media(self) -> bool:
        return bool(self.media)
