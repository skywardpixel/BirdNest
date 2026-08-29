"""Filename construction (DESIGN.md 1)."""
from __future__ import annotations

import re
from pathlib import Path

DEFAULT_TEMPLATE = "{author}_{id}"
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize(value: str, maxlen: int = 60) -> str:
    value = _UNSAFE.sub("", str(value)).strip(" .")
    value = re.sub(r"\s+", " ", value)
    return (value[:maxlen].strip() or "untitled")


def stem_for(tweet, item, template: str = DEFAULT_TEMPLATE, total: int = 1) -> str:
    stem = template.format(
        author=sanitize(tweet.author, 30),
        id=tweet.id,
        date=tweet.created_at.strftime("%Y%m%d") if tweet.created_at else "",
        kind=item.kind,
    )
    if total > 1:
        stem = f"{stem}_{item.index + 1}"
    return sanitize(stem, 120)


def unique(path: Path) -> Path:
    """Never clobber: foo.mp4 -> foo-2.mp4."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not cand.exists():
            return cand
    raise FileExistsError(path)
