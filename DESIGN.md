# BirdNest — design

A local CLI for saving videos and GIFs from Twitter/X, with sane filenames,
metadata sidecars, and true-GIF conversion.

## 1. The core problem

Extraction is the hard part, and it is a moving target: X gates tweet payloads
behind rotating GraphQL endpoints, guest-token rules, and auth checks that break
every few months. Writing our own extractor means signing up to maintain it.

**Decision: BirdNest does not implement extraction. It wraps `yt-dlp` as a
library** (`yt_dlp.YoutubeDL`), which already tracks X's API churn and ships
extractors for `twitter`, `twitter:amplify`, `twitter:card`, `twitter:broadcast`
and `twitter:spaces`.

BirdNest's value is everything yt-dlp is deliberately generic about:

| Concern | Raw yt-dlp | BirdNest |
|---|---|---|
| URL forms (`x.com`, `twitter.com`, `/photo/1`, `?s=20`, `vx`/`fx` mirrors) | partial | normalized up front |
| Animated GIFs | saves the silent MP4 X actually serves | detects `animated_gif`, optional real `.gif` transcode |
| Filenames | generic template | `{author}_{id}_{n}.{ext}`, configurable |
| Provenance | none | JSON sidecar: tweet text, author, date, source URL, sha256 |
| Re-downloading the same tweet | re-fetches | manifest-backed dedupe |
| Batch / clipboard / macOS integration | none | built in |

## 2. Facts that shape the design

- **X "GIFs" are not GIFs.** They are silent, looping H.264 MP4s served from
  `video.twimg.com/tweet_video/<hash>.mp4`, exposed as media type
  `animated_gif` with a single variant. Default behaviour is to keep the MP4
  (small, high quality); `--gif` transcodes.
- **Videos** carry several progressive MP4 variants plus an HLS `m3u8`. Best
  quality is usually the top-bitrate progressive; HLS occasionally goes higher
  and needs ffmpeg to mux. `-f 'bv*+ba/b'` covers both.
- **Auth.** Protected, age-gated, and an increasing share of ordinary tweets need
  a logged-in session. Support `--cookies-from-browser {safari,chrome,firefox}`.
  Safari cookie extraction requires Full Disk Access for the terminal.
- **Real GIF output is expensive.** A 20s 720p clip becomes tens of MB. Default
  the transcode to `fps=15`, `width=480`, two-pass palette.

## 3. Architecture

```
URL/ID in ──▶ urls.normalize ──▶ resolve.chain ──▶ select ──▶ download ──▶ postprocess ──▶ store
             (parse & dedupe)    (yt-dlp,          (quality/  (yt-dlp)     (ffmpeg:        (naming,
                                  fx fallback)      kind)                   gif/remux)      manifest)
```

A thin, testable pipeline: every stage takes and returns plain dataclasses, so
resolution can be unit-tested against recorded JSON with no network.

### Data model (`models.py`)

```python
@dataclass(frozen=True)
class Variant:
    url: str; kind: Literal["mp4", "hls"]
    width: int | None; height: int | None; bitrate: int | None

@dataclass(frozen=True)
class MediaItem:
    index: int                                   # position within the tweet
    kind: Literal["video", "animated_gif"]
    duration_s: float | None
    variants: tuple[Variant, ...]

@dataclass(frozen=True)
class Tweet:
    id: str; author: str; created_at: datetime
    text: str; url: str; media: tuple[MediaItem, ...]
```

### Resolver chain (`resolve/`)

A `Resolver` protocol with `resolve(tweet_id) -> Tweet`, tried in order:

1. `ytdlp.py` — `YoutubeDL({"skip_download": True}).extract_info(url, download=False)`,
   mapped into our model. Primary path.
2. `fxtwitter.py` — `https://api.fxtwitter.com/status/<id>` returns plain JSON
   media URLs with no auth. Useful when yt-dlp's extractor is mid-breakage.
   Third-party, so it is a fallback and never the default. *Verify it still
   behaves as described before wiring it up.*

Chain failures aggregate into one error listing what each resolver said, rather
than surfacing whichever exception happened to come last.

### Download (`download.py`)

Delegate to yt-dlp — it handles HLS segment muxing, resume, and throttling. Write
to `.part` in a temp dir and `os.replace` into place, so an interrupted run never
leaves a half-file that dedupe would later mistake for complete.

### Post-process (`postprocess.py`)

Two-pass palette transcode, which is the difference between an acceptable GIF and
a banded one:

```
ffmpeg -i in.mp4 -vf "fps=15,scale=480:-1:flags=lanczos,split[a][b];
  [a]palettegen=stats_mode=diff[p];
  [b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" -loop 0 out.gif
```

Also: `-metadata comment=<source url>` embedded into MP4s, so a file that drifts
out of the download directory still knows where it came from.

### Store (`store.py`)

SQLite at `~/.local/share/birdnest/manifest.db`, one row per downloaded media
item keyed `(tweet_id, index)`, holding path, sha256, size, and fetch time.
Powers `--skip-existing` (default on) and `birdnest list`. SQLite over JSONL
because the clipboard watcher does one lookup per paste and concurrent runs
should not corrupt it.

## 4. CLI surface

```
birdnest <url|id>...                 # download; the 90% case
birdnest --gif <url>                 # transcode animated_gif → real .gif
birdnest --from-file urls.txt        # batch; also reads stdin
birdnest --thread <url>              # every media item in the thread
birdnest serve                       # local daemon the Chrome extension talks to
birdnest list [--author X]           # query the manifest
birdnest open <id>                   # reveal in Finder

  -o, --out DIR              default ~/Downloads/BirdNest
  -q, --quality best|720|480
  --gif [--fps N --width N]
  --cookies-from-browser B
  --audio / --no-audio
  --copy                     put the finished file on the macOS pasteboard
  --json                     machine-readable result, for scripting
  --dry-run                  resolve and print, download nothing
```

Config at `~/.config/birdnest/config.toml` supplies defaults for `out`,
`quality`, naming template, and cookie browser.

## 5. Chrome integration (primary front-end)

The goal is grabbing media while browsing X in Chrome, not copying links into a
terminal. This **replaces** the clipboard-polling `watch` mode from the first
draft — that was a workaround for exactly this gap.

### 5.1 Why the extension owns no extraction logic

Tempting: the extension reads the `<video>` element's `src` and calls
`chrome.downloads.download()`. X plays video two ways, and only one of them
cooperates:

- **Animated GIFs and some short clips** — `<video src>` is a direct
  `https://video.twimg.com/tweet_video/<hash>.mp4`. Downloadable as-is, and
  §5.2 keeps this fast path in the extension.
- **Longer videos** — Media Source Extensions + HLS. The `src` is a `blob:`
  URL backed by an in-memory buffer. There is nothing to hand to
  `chrome.downloads`, and X serves audio and video as separate renditions, so
  the segments need real muxing, not concatenation.

The rule that follows is narrower than "the extension never downloads": the
extension may take the direct-URL fast path, but it **never learns how to find
a media URL**. Anything requiring interpretation of X's payloads goes to
yt-dlp. Extraction is the part that breaks every few months (§1), and it should
break in a dependency we upgrade, not in code we own.

Reimplementing HLS in the extension is possible — fetch the manifest, pull
segments, mux with ffmpeg.wasm — and is rejected: a ~30 MB wasm payload
duplicating what yt-dlp and a native ffmpeg already do correctly.

### 5.2 What needs a native process, and what does not

| Task | Extension alone? |
|---|---|
| Save animated GIF / short MP4 (direct `video.twimg.com` URL) | yes — `chrome.downloads` |
| Save long video (HLS, separate audio + video renditions) | no — needs ffmpeg to mux |
| Real `.gif` transcode | no — needs ffmpeg |
| **Copy to clipboard** | **no — impossible in-browser** |

The clipboard row is a hard platform limit, not a preference. Chrome's async
clipboard API writes only a sanitised set of types — `text/plain`, `text/html`,
`image/png`. There is no `video/mp4`; `image/gif` is unsupported, so animation
is lost; and `public.file-url` (the native type that makes a paste arrive as a
*file*, per §5.5) has no web API at all. Chrome's "web custom formats" do not
bridge this — they are namespaced for other web apps and never surface as native
pasteboard types.

Consequence: for plain "save this GIF" BirdNest **is** a pure extension. The
native helper is reached only for clipboard copy, HLS muxing, and GIF transcode.

### 5.3 Transport: native messaging, not a daemon

**Revised from the previous draft**, which specified a long-running HTTP server
on `127.0.0.1` under a LaunchAgent, with a bearer token and CORS. That was more
machinery than the job needs.

`chrome.runtime.connectNative` has Chrome spawn the helper on demand, keep it
alive for the length of the connection (enough to stream download progress
back), and let it exit. No resident process, no open port, no token, no CORS,
and no origin validation — Chrome will only connect an extension listed in the
host manifest's `allowed_origins`. The entire loopback-port threat model from
the earlier draft disappears, since there is no port for other pages to reach.

One consequence of on-demand spawning: the helper is re-executed per
connection, so changes to the Python side take effect on the next click with no
extension reload. It also inherits launchd's minimal environment rather than a
shell's — see the ffmpeg row in §6, which is the first thing that bit.

The debuggability argument that previously favoured HTTP is recoverable: the
helper and the CLI are one entry point, so development happens through
`birdnest ...` directly and stdio framing is only exercised in production.

Install is two steps, once:

1. Load the unpacked extension in Chrome.
2. `birdnest install-host` — writes
   `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.birdnest.host.json`.

Pin `key` in the extension manifest so the extension ID stays stable; the host
manifest hardcodes that ID in `allowed_origins` and otherwise breaks silently
whenever an unpacked extension is reloaded from a different path.

*Keep the HTTP daemon as a documented fallback only* — it is the escape hatch if
native messaging proves awkward, and it is what a future non-Chrome front-end
(Quick Action, bookmarklet, Safari) would share.

### 5.3a Auth, revisited

The extension can read media URLs from X's own GraphQL traffic in the page,
which is **already authenticated as the logged-in user**. Where that works it
removes the need for `--cookies-from-browser` on the native side entirely, and
may render §8 step 0 moot. The CLI still needs the cookie path for standalone
use with no browser in the loop.

### 5.4 UX: context menu first, injected buttons later

**Stage 1 — `chrome.contextMenus`. Partly invalidated by testing (2026-08-29).**
X's video player calls `preventDefault()` on `contextmenu` and renders its own
menu ("Copy video address" / "Post Video"), so Chrome's native menu never opens
over a video — and `chrome.contextMenus` items exist only in that native menu.
The context-menu-first plan was chosen to dodge DOM fragility, but it cannot
reach the one element that matters. It still works when right-clicking tweet
text or the page around a video, so it is kept, not removed.

**Stage 1b — triggers the page cannot intercept.** A toolbar-icon click
(`chrome.action.onClicked`) and hotkeys (`chrome.commands`, ⌘⇧E copy / ⌘⇧Y
save) never pass through the page's event handlers, so X cannot swallow them.
Target selection comes from a capture-phase `mouseover` listener tracking the
last hovered player — capture phase is also why the right-clicked node is still
recorded even when X suppresses the menu.

**Stage 2 — injected buttons. Built, no longer deferred.** A ⇩ control in the
top-right of every player: click copies, shift-click saves. With the context
menu unreachable over a video this is the primary trigger, not a nicety, so the
maintenance burden it carries is now unavoidable rather than optional.

Mechanics that matter: a `MARK` attribute guards against double-injection as X
recycles nodes through its virtualised timeline; the MutationObserver is
debounced at 250 ms because X mutates the DOM continuously; and the click
handler runs in the capture phase with `stopPropagation`, since X treats a
click anywhere in the player as play/pause and would otherwise toggle playback
underneath the button.

Chrome hands the handler `pageUrl`, which on a timeline is the timeline, not the
tweet. So a small content script records the last right-clicked element and
resolves it on demand:

```js
// walk up from the clicked node to the tweet card, then read its permalink
const article = el.closest('article[data-testid="tweet"]');
const href = article?.querySelector('a[href*="/status/"] time')
                     ?.closest('a')?.getAttribute('href');   // /user/status/<id>
```

Caveats to handle: single-tweet pages resolve from `location.pathname`; the
lightbox uses `/status/<id>/video/1`; **quoted tweets nest inside the outer
article** as `div[role="link"]` rather than a nested `<article>`, so naive
`closest()` attributes the quote's media to the wrong tweet. Multi-media tweets
need the media's index within the card, not just the ID. *X's markup shifts —
verify all of these against the live DOM before relying on them; `data-testid`
values are the most stable handles available but are not a contract.*

**Stage 2 — injected buttons**, a download affordance on each video in the
timeline. Better UX, but it needs a MutationObserver against a virtualized,
recycling infinite scroll, guarded with a `data-birdnest` marker against double
injection. This is where essentially all ongoing maintenance will live, which is
why it is stage 2 and not stage 1.

Feedback: badge text via `chrome.action.setBadgeText` while a job runs, then a
notification. The daemon exposes `GET /jobs/<id>` for status.

### 5.5 "Copy" — two different things

Worth separating, because they need different machinery:

- **Copy to disk** (save it, then reveal in Finder) — the pipeline as designed.
- **Copy to the pasteboard**, to paste into Messages/Slack/Notes — this is why
  pyobjc is a dependency. An extension cannot write the macOS pasteboard; the
  daemon does it after download, writing an `NSPasteboardTypeFileURL` via
  `NSPasteboard.generalPasteboard().writeObjects_([NSURL.fileURLWithPath_(p)])`.

A file-URL paste is the reliable form for video — target apps attach the file.
Pasting raw video *bytes* (e.g. under `public.mpeg-4`) is a dead end: almost
nothing reads video data off the pasteboard.

**The clipboard holds a reference, so the file must outlive the copy.** A paste
happening minutes later re-resolves that path. Copy-mode therefore must not
download into a `TemporaryDirectory()` that is cleaned on exit — the paste would
fail silently and look like the tool did nothing. Copies land in a durable cache
(`~/Library/Caches/BirdNest/`) pruned only by age, never at process exit.

Corollary: "copy directly" cannot skip the download. The UX can hide it —
right-click, background fetch, clipboard populated on completion — but a long
video takes as long as it takes, so the badge/notification feedback in §5.4 is
required here, not optional.

NSPasteboard holds **multiple representations of one item**, so for GIFs write
both the file URL and the raw bytes under `com.compuserve.gif`; apps that paste
GIFs inline take the animation, everything else takes the file. AppleScript
cannot express multi-representation items — this is the reason the daemon uses
pyobjc rather than shelling out to `osascript`.

**Do not advertise a plain-text representation.** It is tempting to add the
path as `public.utf8-plain-text` so *something* pastes everywhere. Rejected as
the default: representations are offered in preference order and an app picks
the first type it understands, so any app that favours text would paste
`/Users/…/clip.mp4` into a Slack message when it could have attached the video.
Failing to paste is a better error than pasting a path that means nothing on
anyone else's machine. Offer it behind a config flag only.

The target behaviour is exactly Finder's ⌘C on a file — same pasteboard type,
same result. That is the bar: if a given app accepts a file pasted from Finder,
it accepts a BirdNest copy, and no app-specific work is needed.

*Verified 2026-08-29:* writing an `NSPasteboardTypeFileURL` item via pyobjc and
reading it back succeeds. (`osascript`/`pbpaste` **are** isolated in a sandboxed
shell and silently no-op — a misleading earlier signal; the pyobjc path is not
affected.) What remains unverified is per-app paste *rendering*, which only a
real Cmd-V into Messages/Slack/Notes can settle.

## 6. Failure modes to handle explicitly

| Case | Behaviour |
|---|---|
| Tweet deleted / suspended account | clear message, exit 4, no traceback |
| Auth required | name `--cookies-from-browser` in the error, exit 5 |
| Rate limited (429) | exponential backoff, 3 tries, then defer and continue the batch |
| Photo-only tweet | exit 3, message naming both causes. **Revised after live testing:** yt-dlp returns the same "No video could be found" text for a photo-only tweet and a nonexistent one, so exit 0 would let a batch silently skip deleted tweets |
| ffmpeg missing | fail only for `--gif` and HLS, never for progressive MP4 |
| Batch partial failure | finish the rest, print a summary of failures, exit 1 |
| ffmpeg "not installed" while plainly installed | Chrome spawns the host via launchd with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, which excludes `/opt/homebrew/bin`. Resolve ffmpeg by absolute path (`postprocess.find_ffmpeg`), pass it to yt-dlp as `ffmpeg_location`, and prepend its directory to `PATH`. Hit for real on 2026-08-29 |
| Native host not installed | Chrome reports the port closing immediately; extension surfaces "run `birdnest install-host`" rather than a generic failure |
| Extension can't resolve the tweet from the DOM | fall back to `pageUrl`; if that is a timeline, say so rather than downloading the wrong tweet |

Concurrency capped at 3, per-download retries with jitter.

## 7. Layout & dependencies

```
birdnest/{cli,urls,models,download,postprocess,naming,store,config,clipboard}.py
birdnest/resolve/{__init__,ytdlp,fxtwitter}.py
tests/fixtures/*.json          # recorded payloads: video, gif, multi-media, thread
```

`uv` project; deps `yt-dlp`, `httpx`, `rich` (progress), `platformdirs`,
`pyobjc-framework-Cocoa` (pasteboard). Plus `extension/` — MV3 manifest,
service worker, content script — with no build step, loaded unpacked.
Tests run offline against fixtures; a small opt-in `--network` suite catches
extractor breakage.

## 8. Build order

0. ~~Confirm yt-dlp resolves a real public X video URL unauthenticated today.~~
   **Answered 2026-08-29:** a real tweet resolved through the extension with no
   cookies configured — extraction got as far as selecting formats and only the
   ffmpeg merge failed. Cookies stay opt-in.
1. `urls.py` + `models.py` + `resolve/ytdlp.py` + `--dry-run`. Prints what it
   found; no writes. Verifiable end-to-end on day one.
2. Download + naming + sidecar. Now genuinely useful from the CLI.
3. Native host entry point, driven directly from the CLI first — the stdio
   framing is the last thing wired up, not the first.
4. MV3 extension, context-menu only, wired to the daemon. **This is the point
   where the thing you actually asked for works.**
5. `--copy` pasteboard support, then `--gif`.
6. `store.py` dedupe, batch, threads, error taxonomy.
7. Injected timeline buttons, if the right-click flow proves too slow.

## 9. Scope note

Aimed at personal archiving of individual tweets. Bulk scraping of whole
accounts is out of scope by design — it is what draws rate limits and what X's
terms specifically target. Downloaded media stays someone else's copyrighted
work; saving it locally and redistributing it are different things.
