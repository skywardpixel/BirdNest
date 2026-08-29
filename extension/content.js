// Resolves which tweet (and which media within it) was targeted, and injects
// the download buttons. This is the only part coupled to X's DOM, and so the
// part expected to need maintenance — see DESIGN.md 5.4.

let lastTarget = null;   // last right-clicked node
let lastMedia = null;    // last hovered player, for triggers X cannot intercept

// Capture phase: records the node even though X's player calls preventDefault()
// on contextmenu and swallows Chrome's native menu entirely.
document.addEventListener("contextmenu", (e) => { lastTarget = e.target; }, true);

const MEDIA_SEL = '[data-testid="videoPlayer"], video';
document.addEventListener("mouseover", (e) => {
  const el = e.target;
  if (el && el.nodeType === 1 && el.closest && el.closest(MEDIA_SEL)) {
    lastMedia = el;
  }
}, true);

function tweetIdFromPath() {
  const m = location.pathname.match(/\/status\/(\d+)/);
  return m ? m[1] : null;
}

function scopeFor(el) {
  // A quoted tweet is a div[role="link"] nested INSIDE the outer <article>, so
  // a naive closest('article') would credit quoted media to the quoting tweet.
  const quoted = el.closest('div[role="link"]');
  if (quoted && quoted.querySelector('a[href*="/status/"]')) return quoted;
  return el.closest('article[data-testid="tweet"]');
}

function resolve(node) {
  const el = node && (node.nodeType === 1 ? node : node.parentElement);
  if (!el) {
    const id = tweetIdFromPath();
    return id ? { tweetId: id, index: 0 } : null;
  }

  const scope = scopeFor(el);
  if (!scope) {
    const id = tweetIdFromPath();
    return id ? { tweetId: id, index: 0 } : null;
  }

  let author = null, tweetId = null;
  for (const a of scope.querySelectorAll('a[href*="/status/"]')) {
    const m = (a.getAttribute("href") || "").match(/^\/([^/]+)\/status\/(\d+)/);
    if (m) { author = m[1]; tweetId = m[2]; break; }
  }
  if (!tweetId) {
    // Lightbox and some overlays keep the id in the URL but not in the card.
    tweetId = tweetIdFromPath();
    if (!tweetId) return null;
  }

  let players = [...scope.querySelectorAll('[data-testid="videoPlayer"]')];
  if (players.length === 0) players = [...scope.querySelectorAll("video")];
  let index = players.findIndex((p) => p === el || p.contains(el));
  if (index < 0) index = 0;

  return { tweetId, author, index };
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.type !== "resolve") return;
  // A context-menu click knows exactly what was clicked; a toolbar click or
  // hotkey does not, so fall back to whatever player was last hovered.
  const node = msg.source === "context"
    ? (lastTarget || lastMedia)
    : (lastMedia || lastTarget);
  reply(resolve(node));
  return true;
});

// ---------------------------------------------------------------------------
// Injected buttons (DESIGN.md 5.4 stage 2).
//
// Promoted from "deferred" after testing showed X's player calls
// preventDefault() on contextmenu, leaving Chrome's native menu — and every
// chrome.contextMenus item — unreachable over a video. A button in the page is
// the only trigger sitting where the user is already looking.
// ---------------------------------------------------------------------------

const MARK = "data-birdnest";

const BUTTONS = [
  { glyph: "\u29C9", action: "copy", title: "BirdNest — copy to clipboard" },
  { glyph: "\u21E9", action: "save", title: "BirdNest — save to Downloads" },
];

function run(btn, player, action) {
  const found = resolve(player);
  if (!found || !found.tweetId) {
    btn.textContent = "?";
    setTimeout(() => { btn.textContent = btn.dataset.idleGlyph; }, 2000);
    return;
  }
  btn.textContent = "\u2026";
  chrome.runtime.sendMessage({ type: "grab", action, gif: false, found }, (res) => {
    btn.textContent = res && res.ok ? "\u2713" : "!";
    setTimeout(() => { btn.textContent = btn.dataset.idleGlyph; }, 2000);
  });
}

function makeButton(spec, player) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = spec.glyph;
  btn.dataset.idleGlyph = spec.glyph;   // survives rapid re-clicks mid-state
  btn.title = spec.title;
  Object.assign(btn.style, {
    width: "34px", height: "34px", borderRadius: "17px",
    border: "none", background: "rgba(0,0,0,0.65)", color: "#fff",
    font: "15px/1 system-ui, sans-serif", cursor: "pointer", padding: "0",
    display: "flex", alignItems: "center", justifyContent: "center",
    transition: "background 120ms",
  });
  btn.addEventListener("mouseenter", () => {
    btn.style.background = "rgba(29,161,242,0.95)";
  });
  btn.addEventListener("mouseleave", () => {
    btn.style.background = "rgba(0,0,0,0.65)";
  });
  // Capture phase + stopPropagation: X treats a click anywhere in the player
  // as play/pause and would otherwise toggle playback underneath the button.
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    run(btn, player, spec.action);
  }, true);
  return btn;
}

function inject(player) {
  if (!player || player.nodeType !== 1 || player.getAttribute(MARK)) return;
  player.setAttribute(MARK, "1");

  if (getComputedStyle(player).position === "static") {
    player.style.position = "relative";
  }

  const bar = document.createElement("div");
  Object.assign(bar.style, {
    position: "absolute", top: "8px", right: "8px", zIndex: "10001",
    display: "flex", gap: "6px",
  });
  bar.addEventListener("click", (e) => e.stopPropagation(), true);

  for (const spec of BUTTONS) bar.appendChild(makeButton(spec, player));
  player.appendChild(bar);
}

function scan() {
  for (const p of document.querySelectorAll('[data-testid="videoPlayer"]')) {
    inject(p);
  }
  for (const v of document.querySelectorAll("video")) {
    if (!v.closest("[" + MARK + "]")) inject(v.parentElement);
  }
}

let pending = null;
const observer = new MutationObserver(() => {
  if (pending) return;                    // debounce: X mutates constantly
  pending = setTimeout(() => { pending = null; scan(); }, 250);
});

observer.observe(document.body, { childList: true, subtree: true });
scan();
console.log("[BirdNest] content script active");
