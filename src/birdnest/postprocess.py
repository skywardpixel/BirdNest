"""ffmpeg work: locating it, and the real .gif transcode (DESIGN.md 3)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import FFmpegMissing

# Chrome spawns the native messaging host via launchd with a minimal
# environment — PATH is roughly /usr/bin:/bin:/usr/sbin:/sbin, which excludes
# every package manager's prefix. shutil.which() alone therefore fails inside
# the host even when ffmpeg is plainly installed for the user's shell.
CANDIDATE_DIRS = (
    "/opt/homebrew/bin",   # Homebrew, Apple silicon
    "/usr/local/bin",      # Homebrew, Intel
    "/opt/local/bin",      # MacPorts
    "/usr/bin",
)


def find_ffmpeg() -> str | None:
    """Absolute path to ffmpeg, independent of the inherited PATH."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for directory in CANDIDATE_DIRS:
        candidate = Path(directory) / "ffmpeg"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def ensure_on_path() -> str | None:
    """Put ffmpeg's directory on PATH for anything that shells out later."""
    found = find_ffmpeg()
    if found:
        directory = str(Path(found).parent)
        current = os.environ.get("PATH", "")
        if directory not in current.split(os.pathsep):
            os.environ["PATH"] = directory + os.pathsep + current
    return found


def have_ffmpeg() -> bool:
    return find_ffmpeg() is not None


def to_gif(src: Path, dest: Path, fps: int = 15, width: int = 480) -> Path:
    """Two-pass palette transcode.

    A single pass quantises to a generic palette and bands badly; generating a
    palette from the clip's own colours is the whole difference in quality.
    """
    exe = find_ffmpeg()
    if not exe:
        raise FFmpegMissing("ffmpeg is required for --gif but was not found")

    vf = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    )
    tmp = dest.with_suffix(".gif.part")
    proc = subprocess.run(
        [exe, "-y", "-loglevel", "error", "-i", str(src),
         "-vf", vf, "-loop", "0", str(tmp)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise FFmpegMissing(f"ffmpeg failed: {proc.stderr.strip()[:400]}")
    tmp.replace(dest)
    return dest


def tag_source(path: Path, source_url: str) -> None:
    """Embed the tweet URL so a file that drifts still knows its origin."""
    exe = find_ffmpeg()
    if path.suffix.lower() != ".mp4" or not exe:
        return
    tmp = path.with_suffix(".tagged.mp4")
    proc = subprocess.run(
        [exe, "-y", "-loglevel", "error", "-i", str(path),
         "-c", "copy", "-metadata", f"comment={source_url}", str(tmp)],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and tmp.exists():
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)
