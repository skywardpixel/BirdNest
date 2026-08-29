"""Downloading, delegated to yt-dlp (DESIGN.md 3)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .errors import classify
from .models import MediaItem, Tweet
from .naming import unique
from .postprocess import find_ffmpeg

QUALITY = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480]+ba/b[height<=480]/b",
}


def _downloaded_path(info: dict) -> Path | None:
    """Dig the final filename out of a yt-dlp result."""
    for node in (info, *(info.get("entries") or [])):
        if not node:
            continue
        for req in (node.get("requested_downloads") or []):
            fp = req.get("filepath") or req.get("_filename")
            if fp:
                return Path(fp)
    return None


def fetch(
    tweet: Tweet,
    item: MediaItem,
    dest_dir: Path,
    stem: str,
    *,
    resolver,
    quality: str = "best",
    audio: bool = True,
    progress=None,
) -> Path:
    """Download one media item, landing it atomically in `dest_dir`.

    Staged through a temp directory so an interrupted run never leaves a partial
    file that dedupe would later mistake for a finished one.
    """
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    fmt = QUALITY.get(quality, QUALITY["best"])
    if not audio:
        fmt = "bv*/b"

    # Staged inside dest_dir, not /tmp: os.replace() cannot cross filesystems,
    # and dest may be an external drive or network mount.
    with tempfile.TemporaryDirectory(prefix=".birdnest-", dir=dest_dir) as tmp:
        opts = resolver.base_opts() | {
            "format": fmt,
            "outtmpl": {"default": str(Path(tmp) / "media.%(ext)s")},
            "merge_output_format": "mp4",
            # A tweet with several videos resolves as a playlist; 1-based.
            "playlist_items": str(item.index + 1),
        }
        # Merging DASH/HLS renditions needs ffmpeg, and the native host does
        # not inherit a PATH that finds it (see postprocess.CANDIDATE_DIRS).
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        if progress:
            opts["progress_hooks"] = [progress]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(item.source_url or tweet.url, download=True)
        except Exception as exc:
            raise classify(str(exc)) from exc

        got = _downloaded_path(info)
        if got is None or not got.exists():
            produced = list(Path(tmp).iterdir())
            if not produced:
                raise classify("yt-dlp produced no file")
            got = produced[0]

        final = unique(dest_dir / f"{stem}{got.suffix}")
        got.replace(final)   # atomic: same filesystem by construction
        return final
