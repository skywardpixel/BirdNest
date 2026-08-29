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

  return { tweetId, author, index, isGif: looksLikeGif(scope) };
}

// X labels animated GIFs with a small "GIF" pill inside the player. There is no
// stabler client-side signal; the host re-checks authoritatively from the media
// payload, so a wrong guess here only affects which menu items look enabled.
function looksLikeGif(scope) {
  for (const el of scope.querySelectorAll("span, div")) {
    if (el.childElementCount === 0 && el.textContent.trim() === "GIF") return true;
  }
  return false;
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
const MENU_CLASS = "birdnest-menu";

const MENU_ITEMS = [
  { action: "copy", gif: false, glyph: "\u29C9", label: "Copy to clipboard" },
  { action: "save", gif: false, glyph: "\u21E9", label: "Save to Downloads" },
  { action: "copy", gif: true, glyph: "\u25CD", label: "Copy as animated GIF" },
  { action: "save", gif: true, glyph: "\u25CE", label: "Save as animated GIF" },
];

function closeMenus() {
  for (const m of document.querySelectorAll("." + MENU_CLASS)) m.remove();
}

document.addEventListener("click", closeMenus, true);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenus();
}, true);

function buildMenu(player, btn, found) {
  closeMenus();

  const menu = document.createElement("div");
  menu.className = MENU_CLASS;
  Object.assign(menu.style, {
    position: "absolute", top: "48px", right: "8px", zIndex: "10000",
    minWidth: "196px", padding: "4px", borderRadius: "10px",
    background: "rgba(21,32,43,0.97)", color: "#fff",
    font: "13px/1.4 system-ui, -apple-system, sans-serif",
    boxShadow: "0 6px 24px rgba(0,0,0,0.45)",
    border: "1px solid rgba(255,255,255,0.14)",
  });

  for (const item of MENU_ITEMS) {
    const disabled = item.gif && found.isGif === false;
    const row = document.createElement("div");
    row.textContent = item.glyph + "   " + item.label;
    Object.assign(row.style, {
      padding: "8px 10px", borderRadius: "7px",
      cursor: disabled ? "default" : "pointer",
      opacity: disabled ? "0.4" : "1", whiteSpace: "nowrap",
    });
    if (disabled) {
      row.title = "This media is a video, not an animated GIF";
    } else {
      row.addEventListener("mouseenter", () => {
        row.style.background = "rgba(255,255,255,0.12)";
      });
      row.addEventListener("mouseleave", () => { row.style.background = ""; });
      row.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeMenus();
        run(btn, found, item.action, item.gif);
      }, true);
    }
    menu.appendChild(row);
  }

  // Clicks inside the menu must not reach X's player (it toggles playback).
  menu.addEventListener("click", (e) => e.stopPropagation(), true);
  player.appendChild(menu);
}

function run(btn, found, action, gif) {
  btn.textContent = "\u2026";
  chrome.runtime.sendMessage({ type: "grab", action, gif, found }, (res) => {
    btn.textContent = res && res.ok ? "\u2713" : "!";
    setTimeout(() => { btn.textContent = btn.dataset.idleGlyph; }, 2500);
  });
}

function inject(player) {
  if (!player || player.nodeType !== 1 || player.getAttribute(MARK)) return;
  player.setAttribute(MARK, "1");

  if (getComputedStyle(player).position === "static") {
    player.style.position = "relative";
  }

  const isGif = looksLikeGif(player);
  const btn = document.createElement("button");
  btn.type = "button";
  // The idle glyph reflects what the media actually is, so the control reads
  // differently on a GIF than on a video before anything is clicked.
  btn.dataset.idleGlyph = isGif ? "\u25CD" : "\u21E9";
  btn.textContent = btn.dataset.idleGlyph;
  btn.title = isGif ? "BirdNest — animated GIF" : "BirdNest — video";
  Object.assign(btn.style, {
    position: "absolute", top: "8px", right: "8px", zIndex: "10001",
    width: "34px", height: "34px", borderRadius: "17px",
    border: "none", background: "rgba(0,0,0,0.65)", color: "#fff",
    font: "16px/1 system-ui, sans-serif", cursor: "pointer", padding: "0",
    display: "flex", alignItems: "center", justifyContent: "center",
  });

  // Capture phase + stopPropagation: X treats a click anywhere in the player
  // as play/pause and would otherwise toggle playback underneath the menu.
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (player.querySelector("." + MENU_CLASS)) { closeMenus(); return; }
    const found = resolve(player);
    if (!found || !found.tweetId) { btn.textContent = "?"; return; }
    buildMenu(player, btn, found);
  }, true);

  player.appendChild(btn);
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
