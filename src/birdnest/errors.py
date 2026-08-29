"""Error taxonomy with the exit codes from DESIGN.md 6."""
from __future__ import annotations


class BirdnestError(Exception):
    exit_code = 1


class TweetUnavailable(BirdnestError):
    """Deleted, suspended, or protected beyond our reach."""
    exit_code = 4


class AuthRequired(BirdnestError):
    """Age-gated or follower-only; needs cookies."""
    exit_code = 5

    def __str__(self) -> str:
        return (f"{super().__str__()}\n"
                "  This tweet needs a logged-in session. Retry with:\n"
                "    birdnest --cookies-from-browser chrome <url>")


class RateLimited(BirdnestError):
    exit_code = 6


class NoMedia(BirdnestError):
    """No video or GIF was found.

    yt-dlp reports "No video could be found in this tweet" for a photo-only
    tweet AND for one that does not exist, so these are indistinguishable from
    the message alone (verified live, 2026-08-29). Exit 3 rather than 0: a
    deleted tweet exiting successfully would let a batch run silently skip it,
    which is worse than a photo-only tweet reporting a non-zero code.
    """
    exit_code = 3


class FFmpegMissing(BirdnestError):
    exit_code = 7


def classify(message: str) -> BirdnestError:
    """Map a yt-dlp error string onto our taxonomy.

    yt-dlp reports everything as DownloadError, so the wording is all we have.
    Unrecognised messages stay generic rather than being forced into a bucket.
    """
    m = (message or "").lower()
    if any(k in m for k in ("nsfw", "age-restricted", "log in", "login required",
                            "requires authentication", "not authorized",
                            "no auth token", "sensitive content")):
        return AuthRequired(message)
    if any(k in m for k in ("rate-limit", "rate limit", "429", "too many requests")):
        return RateLimited(message)
    if any(k in m for k in ("unavailable", "not found", "suspended", "doesn't exist",
                            "does not exist", "deleted", "protected")):
        return TweetUnavailable(message)
    if any(k in m for k in ("no video", "no media", "unsupported url")):
        return NoMedia(message)
    return BirdnestError(message)
