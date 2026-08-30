# BirdNest

Save or copy videos and GIFs from Twitter/X — from a button on the player, a
hotkey, or the command line.

Click the ⇩ on any video and it lands on your clipboard, ready to ⌘V into
Messages, Slack, or Notes. Shift-click saves it to disk instead.

```bash
birdnest https://x.com/user/status/123          # save
birdnest --copy https://x.com/user/status/123   # save and put on the clipboard
birdnest --gif  https://x.com/user/status/123   # transcode a GIF to a real .gif
```

## Why this exists

Three things a browser extension cannot do on its own, which is why BirdNest
pairs one with a small native helper:

- **Copy a video to the clipboard.** Chrome's clipboard API writes only
  `text/plain`, `text/html`, and `image/png`. There is no `video/mp4`, no
  `image/gif`, and no way to write `public.file-url` — the macOS type that makes
  a paste arrive as a *file* rather than a path.
- **Save long videos.** X streams them over HLS with separate audio and video
  renditions behind a `blob:` URL. There is nothing for `chrome.downloads` to
  fetch, and the segments need real muxing.
- **Produce an actual GIF.** X's "GIFs" are silent looping MP4s. Turning one
  into a real `.gif` takes a two-pass palette transcode through ffmpeg.

Extraction itself is delegated to [yt-dlp](https://github.com/yt-dlp/yt-dlp),
which already tracks X's frequently-changing API. BirdNest adds the parts yt-dlp
is deliberately generic about: URL normalisation, GIF handling, filenames,
provenance sidecars, dedupe, and the Chrome and clipboard integration.

## Requirements

macOS, Python 3.11+, [uv](https://docs.astral.sh/uv/), ffmpeg
(`brew install ffmpeg`), and Google Chrome.

## Install

```bash
git clone https://github.com/skywardpixel/BirdNest.git
cd BirdNest
uv sync
uv run birdnest install-host
```

`install-host` generates a signing key, pins it in the extension manifest so the
extension ID stays stable, and registers the native messaging host. Then load
the extension once:

1. Open `chrome://extensions`
2. Enable **Developer mode**, click **Load unpacked**
3. Select the `extension/` directory

The signing key is generated per machine and is gitignored, so your extension ID
is yours alone — `install-host` writes a host manifest matching it.

Note that `install-host` writes the derived public key into
`extension/manifest.json`, which git therefore reports as modified after setup.
That is expected; leave it uncommitted.

## Usage

### In Chrome

| Action | Result |
|---|---|
| ⧉ on a player | Copy to clipboard |
| ⇩ on a player | Save to `~/Downloads/BirdNest/` |
| Click the toolbar icon | Copy the last hovered video |
| ⌘⇧E | Copy the last hovered video |
| ⌘⇧Y | Save the last hovered video |
| Right-click **tweet text** | Context menu (see caveat below) |

X's player intercepts right-click over the video itself and shows its own menu,
so Chrome's native context menu — and every `chrome.contextMenus` entry — is
unreachable there. The button and hotkeys exist because of this.

### Command line

```
birdnest <url|id>...          save media from one or more tweets
  --copy                      also put the file on the macOS clipboard
  --gif [--fps N --width N]   transcode animated GIFs to a real .gif
  --keep-video                with --gif, keep the source mp4 too
  -o, --out DIR               output directory
  -q, --quality best|1080|720|480
  --from-file FILE            batch; also reads stdin
  --cookies-from-browser B    for age-gated or protected tweets
  --dry-run                   resolve and report, write nothing
  --json                      machine-readable output
  --force                     re-download even if already in the manifest

birdnest list [--author X]    show what has been downloaded
birdnest install-host         register the Chrome native messaging host
```

Every download writes a `.json` sidecar with the tweet text, author, date, and
source URL, and is recorded in a SQLite manifest at
`~/Library/Application Support/birdnest/manifest.db` so the same media is not
fetched twice.

Configuration is optional, at `~/.config/birdnest/config.toml`:

```toml
out_dir = "~/Movies/X"
quality = "720"
gif_width = 600
```

## How it works

```
 ┌─ Chrome ──────────────────┐
 │ content script  ⇩ button  │  identifies the tweet; owns no extraction logic
 │        ↓                  │
 │ service worker            │
 └────────┬──────────────────┘
          │ native messaging (stdio; Chrome spawns on demand, no daemon)
          ▼
    birdnest-host ─→ yt-dlp ─→ ffmpeg ─→ NSPasteboard / ~/Downloads
```

There is no background daemon, no localhost port, and no token. Chrome starts
the helper when you click and it exits with the connection.

See [DESIGN.md](DESIGN.md) for the reasoning, including the options that were
rejected and why.

## Troubleshooting

**"ffmpeg is not installed" but it is.** Chrome spawns the helper via launchd
with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, which excludes `/opt/homebrew/bin`.
BirdNest resolves ffmpeg by absolute path to work around this; if you installed
it somewhere unusual, add that directory to `postprocess.CANDIDATE_DIRS`.

**No ⇩ button on videos.** Open DevTools on X and look for
`[BirdNest] content script active`. If it is missing, the extension is not
loaded. If it is present, X has changed its markup and the selectors in
`content.js` need updating — this is the part expected to need maintenance.

**"native host unavailable".** Run `uv run birdnest install-host` again. It also
needs re-running if you move the project directory, since the host manifest
records an absolute path.

**Nothing pastes.** A clipboard copy is a *file reference*, like Finder's ⌘C.
Apps that accept file attachments take the video; a plain-text field gets the
path. The file lives in `~/Library/Caches/BirdNest/` and must stay there for the
paste to resolve.

## Development

```bash
uv run pytest          # 36 tests, no network required
```

The extension icons are generated, not hand-edited:

```bash
uv run --with pillow python tools/make_icon.py
```

They are drawn directly with Pillow rather than rasterised from SVG, because
ImageMagick's built-in SVG renderer silently discarded the gradient and every
stroke and emitted a solid black square.

Resolution is tested against recorded payloads in `tests/fixtures/`, so the
extraction mapping can be checked offline.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with, endorsed by, or connected to X Corp. "Twitter" and "X" are
trademarks of their respective owners.

## Scope

Built for saving individual tweets. Bulk scraping of whole accounts is
deliberately not supported — it is what draws rate limits and what X's terms
target. Downloaded media remains someone else's copyrighted work; saving it
locally and redistributing it are different things.
