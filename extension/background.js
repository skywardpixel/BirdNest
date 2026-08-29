// Service worker: triggers, and the bridge to the native helper.
// Chrome starts the helper on demand; nothing is resident (DESIGN.md 5.3).

const HOST = "com.birdnest.host";
const PATTERNS = ["*://x.com/*", "*://twitter.com/*"];

const MENUS = [
  { id: "save", title: "Save with BirdNest" },
  { id: "copy", title: "Copy with BirdNest" },
  { id: "copygif", title: "Copy as animated GIF" },
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    for (const m of MENUS) {
      chrome.contextMenus.create({
        id: m.id,
        title: m.title,
        contexts: ["video", "image", "link", "page"],
        documentUrlPatterns: PATTERNS,
      });
    }
  });
});

function askContentScript(tabId, source) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, { type: "resolve", source }, (r) => {
      resolve(chrome.runtime.lastError ? null : r);
    });
  });
}

function callHost(payload) {
  return new Promise((resolve) => {
    let port;
    try {
      port = chrome.runtime.connectNative(HOST);
    } catch (e) {
      resolve({ ok: false, error: String(e) });
      return;
    }
    let settled = false;
    port.onMessage.addListener((m) => {
      settled = true;
      resolve(m);
      try { port.disconnect(); } catch (e) { /* already gone */ }
    });
    port.onDisconnect.addListener(() => {
      if (settled) return;
      // Commonest cause by far is the host manifest not being installed.
      const err = (chrome.runtime.lastError && chrome.runtime.lastError.message)
        || "native host unavailable";
      resolve({ ok: false, error: err + " — run: birdnest install-host" });
    });
    port.postMessage(payload);
  });
}


// --- Dynamic toolbar icon -------------------------------------------------
// Drawn at runtime with OffscreenCanvas: an MV3 service worker has no DOM, so
// there is no Image/document to build an icon from. Colour carries the state
// at a glance; the badge still carries the detail.

const ICON_STATES = {
  idle: { bg: "#1DA1F2", glyph: "\u21E9" },
  busy: { bg: "#F5A623", glyph: "\u2026" },
  ok:   { bg: "#17BF63", glyph: "\u2713" },
  err:  { bg: "#E0245E", glyph: "!" },
};

function setIconState(state) {
  const spec = ICON_STATES[state] || ICON_STATES.idle;
  try {
    const size = 128;
    const canvas = new OffscreenCanvas(size, size);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = spec.bg;
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 72px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(spec.glyph, size / 2, size / 2 + 4);
    chrome.action.setIcon({ imageData: ctx.getImageData(0, 0, size, size) });
  } catch (e) {
    // OffscreenCanvas unavailable: the badge alone still conveys state.
  }
}

function badge(text, color) {
  chrome.action.setBadgeText({ text });
  if (color) chrome.action.setBadgeBackgroundColor({ color });
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic", iconUrl: "icon128.png", title, message,
  }, () => void chrome.runtime.lastError);
}

async function runGrab(found, { action, gif }) {
  badge("…", "#1DA1F2");
  setIconState("busy");
  const res = await callHost({
    action, gif,
    tweet_id: found.tweetId,
    author: found.author || null,
    index: found.index || 0,
  });

  if (res && res.ok) {
    badge("✓", "#0a0");
    setIconState("ok");
    notify("BirdNest",
      res.action === "copy" ? "Copied — ⌘V to paste" : "Saved " + res.path);
  } else {
    badge("!", "#b00");
    setIconState("err");
    notify("BirdNest failed", (res && res.error) || "unknown error");
  }
  setTimeout(() => { badge(""); setIconState("idle"); }, 4000);
  return res;
}

// The injected button already knows exactly which player was clicked.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.type !== "grab") return;
  runGrab(msg.found, { action: msg.action, gif: false }).then(reply);
  return true;                                   // keep the channel open
});

async function grab(tabId, { action, gif, source }) {
  const found = await askContentScript(tabId, source);
  if (!found || !found.tweetId) {
    badge("?", "#b00");
    notify("BirdNest",
      "Couldn't tell which tweet that was. Hover the video first, or open the "
      + "tweet on its own page.");
    return;
  }
  return runGrab(found, { action, gif });
}

// X's player calls preventDefault() on contextmenu, so Chrome's native menu
// never opens over a video and these items are unreachable there. They still
// work on tweet text and the page around a video, so they are kept.
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab || !tab.id) return;
  grab(tab.id, {
    action: info.menuItemId === "save" ? "save" : "copy",
    gif: info.menuItemId === "copygif",
    source: "context",
  });
});

// No chrome.action.onClicked here: declaring default_popup in the manifest
// makes Chrome open the popup instead of firing a click handler. The hotkeys
// below remain the one-press path.

chrome.commands.onCommand.addListener((command, tab) => {
  if (!tab || !tab.id) return;
  grab(tab.id, {
    action: command === "grab-save" ? "save" : "copy",
    gif: false,
    source: "command",
  });
});
