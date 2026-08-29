"""macOS pasteboard support (DESIGN.md 5.5).

The clipboard receives a *file reference*, exactly as Finder's Cmd-C does, so
pasting into Messages/Slack/Notes attaches the file rather than a path. This is
the one capability no browser extension can provide.
"""
from __future__ import annotations

import sys
from pathlib import Path

GIF_UTI = "com.compuserve.gif"


class ClipboardUnavailable(RuntimeError):
    pass


def copy_file(path: Path, extra_gif_data: bool = True) -> None:
    """Put `path` on the pasteboard as a file URL.

    For GIFs a second representation carries the raw bytes, so apps that paste
    animations inline get the animation while everything else takes the file.
    A plain-text path representation is deliberately NOT offered (DESIGN.md 5.5).
    """
    if sys.platform != "darwin":
        raise ClipboardUnavailable("clipboard copy is macOS-only")
    try:
        from AppKit import (NSPasteboard, NSPasteboardItem,
                            NSPasteboardTypeFileURL)
        from Foundation import NSData, NSURL
    except ImportError as exc:  # pragma: no cover
        raise ClipboardUnavailable(
            "pyobjc is required for --copy: uv sync") from exc

    path = Path(path).resolve()
    if not path.exists():
        raise ClipboardUnavailable(f"nothing to copy: {path}")

    item = NSPasteboardItem()
    url = NSURL.fileURLWithPath_(str(path))
    if not item.setString_forType_(url.absoluteString(), NSPasteboardTypeFileURL):
        raise ClipboardUnavailable("pasteboard rejected the file URL")

    if extra_gif_data and path.suffix.lower() == ".gif":
        data = NSData.dataWithContentsOfFile_(str(path))
        if data is not None:
            item.setData_forType_(data, GIF_UTI)

    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    if not pb.writeObjects_([item]):
        raise ClipboardUnavailable("pasteboard write failed")


def read_back() -> list[str]:
    """File URLs currently on the pasteboard. Used to verify a copy landed."""
    if sys.platform != "darwin":
        return []
    from AppKit import NSPasteboard, NSPasteboardTypeFileURL
    pb = NSPasteboard.generalPasteboard()
    out = []
    for item in (pb.pasteboardItems() or []):
        s = item.stringForType_(NSPasteboardTypeFileURL)
        if s:
            out.append(str(s))
    return out
