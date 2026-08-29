"""Chrome native-messaging host (DESIGN.md 5.3).

Chrome spawns this on demand and it exits with the connection — there is no
daemon, no port, and no token. Framing is a 4-byte native-endian length prefix
followed by UTF-8 JSON.

Nothing may be written to stdout except framed messages: a stray print corrupts
the stream, which is why this does not reuse the CLI's reporting helpers.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from .config import Config
from .errors import BirdnestError
from .naming import stem_for
from .postprocess import ensure_on_path, to_gif
from .resolve.ytdlp import YtDlpResolver
from .store import Store
from .urls import TweetRef

MAX_MESSAGE = 1 << 20


def _read_message():
    header = sys.stdin.buffer.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("@I", header)
    if length > MAX_MESSAGE:
        raise ValueError("oversized message")
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def _send(payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("@I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def handle(msg: dict, cfg: Config) -> dict:
    action = msg.get("action", "save")
    tweet_id = str(msg.get("tweet_id") or "").strip()
    if not tweet_id.isdigit():
        return {"ok": False, "error": "missing or malformed tweet_id"}

    index = int(msg.get("index") or 0)
    ref = TweetRef(id=tweet_id, author=msg.get("author") or None)
    resolver = YtDlpResolver(cookies_from_browser=cfg.cookies_from_browser)
    tweet = resolver.resolve(ref)

    items = [m for m in tweet.media if m.index == index] or list(tweet.media[:1])
    if not items:
        return {"ok": False, "error": "no video or GIF in that tweet"}
    item = items[0]

    # A clipboard copy is a file reference, so it must outlive this process;
    # copies land in the durable cache, never a temp dir (DESIGN.md 5.5).
    dest = cfg.cache_dir if action == "copy" else cfg.out_dir
    from .download import fetch

    stem = stem_for(tweet, item, cfg.template, total=len(tweet.media))
    path = fetch(tweet, item, dest, stem, resolver=resolver, quality=cfg.quality)

    if msg.get("gif") and item.is_gif:
        gif = path.with_suffix(".gif")
        to_gif(path, gif, fps=cfg.gif_fps, width=cfg.gif_width)
        path.unlink(missing_ok=True)
        path = gif

    if action == "copy":
        from .clipboard import copy_file
        copy_file(path)

    Store(cfg.db_path).record(tweet_id=tweet.id, idx=item.index,
                              author=tweet.author, path=path, kind=item.kind,
                              source_url=tweet.url)
    return {"ok": True, "action": action, "path": str(path),
            "kind": item.kind, "author": tweet.author}


def main() -> int:
    ensure_on_path()   # Chrome gives us a minimal PATH
    cfg = Config.load()
    while True:
        try:
            msg = _read_message()
        except Exception as exc:
            _send({"ok": False, "error": f"bad message: {exc}"})
            return 1
        if msg is None:
            return 0
        try:
            _send(handle(msg, cfg))
        except BirdnestError as exc:
            _send({"ok": False, "error": str(exc), "code": exc.exit_code})
        except Exception as exc:                      # never die mid-connection
            _send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    raise SystemExit(main())
