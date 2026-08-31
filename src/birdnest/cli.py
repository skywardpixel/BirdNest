"""Command line entry point (DESIGN.md 4)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .config import Config
from .errors import BirdnestError, NoMedia
from .models import Tweet
from .naming import stem_for
from .postprocess import ensure_on_path, tag_source, to_gif
from .resolve.ytdlp import YtDlpResolver
from .store import Store
from .urls import NotATweetURL, parse, parse_many

SUBCOMMANDS = {"get", "list", "install-host"}


def _eprint(*a):
    print(*a, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="birdnest", description="Save videos and GIFs from Twitter/X.")
    p.add_argument("--version", action="version", version=f"birdnest {__version__}")
    sub = p.add_subparsers(dest="cmd")

    g = sub.add_parser("get", help="download media from tweets (default)")
    g.add_argument("urls", nargs="*", help="tweet URLs or IDs; reads stdin if empty")
    g.add_argument("-o", "--out", type=Path, help="output directory")
    g.add_argument("-q", "--quality", default=None,
                   choices=["best", "1080", "720", "480"])
    g.add_argument("--from-file", type=Path, help="read URLs from a file")
    g.add_argument("--copy", action="store_true",
                   help="put the finished file on the macOS clipboard")
    g.add_argument("--gif", action="store_true",
                   help="transcode animated GIFs to a real .gif")
    g.add_argument("--keep-video", action="store_true",
                   help="with --gif, keep the source mp4 too")
    g.add_argument("--fps", type=int, default=None, help="gif frame rate")
    g.add_argument("--width", type=int, default=None, help="gif width in px")
    g.add_argument("--no-audio", action="store_true")
    g.add_argument("--cookies-from-browser", default=None,
                   metavar="BROWSER", help="chrome, safari, firefox ...")
    g.add_argument("--force", action="store_true",
                   help="re-download even if the manifest has it")
    g.add_argument("--dry-run", action="store_true",
                   help="resolve and report; write nothing")
    g.add_argument("--json", action="store_true", help="machine-readable output")

    i = sub.add_parser("install-host",
                       help="register the Chrome native-messaging host")
    i.add_argument("--extension-dir", type=Path,
                   default=Path(__file__).resolve().parents[2] / "extension")
    i.add_argument("--browser", default="chrome")

    l = sub.add_parser("list", help="show previously downloaded media")
    l.add_argument("--author")
    l.add_argument("-n", "--limit", type=int, default=25)
    return p


def _inputs(args) -> list:
    raw = list(args.urls)
    if args.from_file:
        raw += args.from_file.read_text().splitlines()
    if not raw and not sys.stdin.isatty():
        raw += sys.stdin.read().splitlines()
    if not raw:
        raise BirdnestError("no tweet URLs given")
    return parse_many(raw)


def _sidecar(tweet: Tweet, item, path: Path) -> None:
    """Provenance next to the file (DESIGN.md 1)."""
    meta = {
        "tweet_id": tweet.id,
        "author": tweet.author,
        "text": tweet.text,
        "created_at": tweet.created_at.isoformat() if tweet.created_at else None,
        "source_url": tweet.url,
        "media_index": item.index,
        "kind": item.kind,
        "best_variant": asdict(item.best) if item.best else None,
        "downloaded_file": path.name,
    }
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False))


def _progress(hook_state: dict):
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total and not hook_state.get("quiet"):
                pct = 100 * done / total
                print(f"\r  {pct:5.1f}%  {done/1e6:6.1f} MB", end="", file=sys.stderr)
        elif d.get("status") == "finished" and not hook_state.get("quiet"):
            print("\r  fetched, finishing up…      ", end="", file=sys.stderr)
    return hook


def cmd_get(args, cfg: Config) -> int:
    refs = _inputs(args)
    out_dir = args.out or cfg.out_dir
    quality = args.quality or cfg.quality
    resolver = YtDlpResolver(
        cookies_from_browser=args.cookies_from_browser or cfg.cookies_from_browser)
    store = None if args.dry_run else Store(cfg.db_path)

    results, failures = [], 0
    for ref in refs:
        try:
            tweet = resolver.resolve(ref)
        except NoMedia as exc:
            _eprint(f"— {ref.canonical_url}: {exc}")
            continue
        except BirdnestError as exc:
            _eprint(f"! {ref.canonical_url}: {exc}")
            failures += 1
            continue

        wanted = tweet.media
        if ref.media_index:                      # /video/2 targets one item
            wanted = tuple(m for m in tweet.media if m.index == ref.media_index - 1)

        for item in wanted:
            label = f"{tweet.author}/{tweet.id}#{item.index + 1}"
            if args.dry_run:
                best = item.best
                dims = f"{best.width}x{best.height}" if best and best.width else "?"
                results.append({"tweet": tweet.url, "kind": item.kind,
                                "index": item.index, "best": dims,
                                "url": best.url if best else None})
                print(f"{label}  {item.kind:13} {dims:>10}  "
                      f"{(item.duration_s or 0):.0f}s")
                continue

            if store and not args.force:
                if hit := store.existing(tweet.id, item.index):
                    print(f"= {label} already at {hit['path']}")
                    results.append({"tweet": tweet.url, "path": hit["path"],
                                    "skipped": True})
                    continue

            from .download import fetch
            stem = stem_for(tweet, item, cfg.template, total=len(tweet.media))
            try:
                print(f"↓ {label}  ({item.kind})", file=sys.stderr)
                path = fetch(tweet, item, out_dir, stem, resolver=resolver,
                             quality=quality, audio=not args.no_audio,
                             progress=_progress({}))
                _eprint("")
                if args.gif and item.is_gif:
                    gif = path.with_suffix(".gif")
                    to_gif(path, gif, fps=args.fps or cfg.gif_fps,
                           width=args.width or cfg.gif_width)
                    if not args.keep_video:
                        path.unlink(missing_ok=True)
                    path = gif
                else:
                    tag_source(path, tweet.url)

                _sidecar(tweet, item, path)
                store.record(tweet_id=tweet.id, idx=item.index, author=tweet.author,
                             path=path, kind=item.kind, source_url=tweet.url)
                print(f"✓ {path}")
                results.append({"tweet": tweet.url, "path": str(path),
                                "kind": item.kind})

                if args.copy:
                    from .clipboard import ClipboardUnavailable, copy_file
                    try:
                        copy_file(path)
                        print(f"⧉ copied to clipboard — ⌘V to paste")
                    except ClipboardUnavailable as exc:
                        _eprint(f"! clipboard: {exc}")
                        failures += 1
            except BirdnestError as exc:
                _eprint(f"\n! {label}: {exc}")
                failures += 1

    if args.json:
        print(json.dumps(results, indent=2))
    return 1 if failures else 0


def cmd_list(args, cfg: Config) -> int:
    rows = Store(cfg.db_path).list(author=args.author, limit=args.limit)
    if not rows:
        print("nothing downloaded yet")
        return 0
    for r in rows:
        size = (r["bytes"] or 0) / 1e6
        print(f"{r['fetched_at']}  {r['author']:<20} {size:7.1f} MB  {r['path']}")
    return 0


def cmd_install_host(args, cfg: Config) -> int:
    from .install import install

    info = install(args.extension_dir, args.browser)
    print(f"✓ host manifest  {info['host_manifest']}")
    print(f"✓ ext manifest   {info['extension_manifest']}")
    print(f"  executable     {info['executable']}")
    print(f"  extension ID   {info['extension_id']}")
    print()
    print("Load the extension once, then it will connect automatically:")
    print(f"  1. open -a 'Google Chrome' chrome://extensions")
    print(f"  2. enable Developer mode, click 'Load unpacked'")
    print(f"  3. choose {info['extension_dir']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Allow `birdnest <url>` with no subcommand.
    if not argv or (argv[0] not in SUBCOMMANDS and not argv[0].startswith("-")):
        argv.insert(0, "get")
    elif argv and argv[0].startswith("-") and argv[0] not in ("--version", "-h", "--help"):
        argv.insert(0, "get")

    args = build_parser().parse_args(argv)
    ensure_on_path()
    cfg = Config.load()
    try:
        if args.cmd == "list":
            return cmd_list(args, cfg)
        if args.cmd == "install-host":
            return cmd_install_host(args, cfg)
        return cmd_get(args, cfg)
    except NotATweetURL as exc:
        _eprint(f"! {exc}")
        return 2
    except BirdnestError as exc:
        _eprint(f"! {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        _eprint("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
