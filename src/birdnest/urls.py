"""Normalise the many shapes an X link arrives in (DESIGN.md 1)."""
from __future__ import annotations

import re
from dataclasses import dataclass

# x.com, the legacy domain, and the embed-fixer mirrors people paste from chat.
_HOSTS = {
    "x.com", "www.x.com", "mobile.x.com",
    "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "vxtwitter.com", "www.vxtwitter.com", "fxtwitter.com", "www.fxtwitter.com",
    "fixupx.com", "www.fixupx.com", "fixvx.com", "twittpr.com",
}

_STATUS = re.compile(
    r"^/(?P<author>[A-Za-z0-9_]{1,15}|i/web|i)"
    r"/status(?:es)?/(?P<id>\d+)"
    r"(?:/(?:photo|video)/(?P<index>\d+))?",
)


class NotATweetURL(ValueError):
    pass


@dataclass(frozen=True)
class TweetRef:
    id: str
    author: str | None = None
    # 1-based in the URL; kept as given so a /video/2 link targets one item.
    media_index: int | None = None

    @property
    def canonical_url(self) -> str:
        return f"https://x.com/{self.author or 'i'}/status/{self.id}"


def parse(raw: str) -> TweetRef:
    """Accept a URL in any known form, or a bare tweet ID."""
    from urllib.parse import urlsplit

    s = (raw or "").strip().strip("<>").strip()
    if not s:
        raise NotATweetURL("empty input")

    if s.isdigit():
        return TweetRef(id=s)

    if "//" not in s:
        s = "https://" + s

    parts = urlsplit(s)
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if host not in _HOSTS:
        raise NotATweetURL(f"not an X link: {raw!r}")

    m = _STATUS.match(parts.path)
    if not m:
        raise NotATweetURL(f"no tweet ID in: {raw!r}")

    author = m.group("author")
    if author in {"i", "i/web"}:
        author = None
    idx = m.group("index")
    return TweetRef(id=m.group("id"), author=author,
                    media_index=int(idx) if idx else None)


def parse_many(lines) -> list[TweetRef]:
    """Parse an iterable of inputs, skipping blanks/comments, de-duplicated."""
    seen: dict[str, TweetRef] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ref = parse(line)
        seen.setdefault(ref.id, ref)
    return list(seen.values())
