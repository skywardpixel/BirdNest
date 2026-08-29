// Toolbar dropdown. Replaces chrome.action.onClicked — Chrome fires the popup
// or the click handler, never both — so the hotkeys remain the one-press path.

const $ = (id) => document.getElementById(id);

function setStatus(text, cls) {
  const el = $("status");
  el.textContent = text;
  el.className = cls || "";
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function askContent(tabId) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, { type: "resolve", source: "popup" }, (r) => {
      resolve(chrome.runtime.lastError ? null : r);
    });
  });
}

let found = null;
let tabId = null;

async function init() {
  const tab = await activeTab();
  if (!tab || !/^https:\/\/(x|twitter)\.com\//.test(tab.url || "")) {
    $("subtitle").textContent = "Open a tweet on x.com to use BirdNest.";
    return;
  }
  tabId = tab.id;
  found = await askContent(tab.id);

  if (!found || !found.tweetId) {
    $("subtitle").textContent =
      "No video found. Hover a video, then reopen this menu.";
    return;
  }

  $("subtitle").textContent = found.author
    ? `@${found.author} · tweet ${found.tweetId}`
    : `tweet ${found.tweetId}`;
  $("actions").hidden = false;

  // The GIF actions only mean anything for X's animated_gif media; the host
  // ignores the flag for ordinary video, so they are hinted rather than hidden.
  if (found.isGif === false) {
    for (const b of document.querySelectorAll('[data-action$="gif"]')) {
      b.disabled = true;
      b.title = "This tweet's media is a video, not an animated GIF";
    }
  }
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn || !found) return;

  const kind = btn.dataset.action;
  setStatus("Working…");
  for (const b of document.querySelectorAll("button")) b.disabled = true;

  chrome.runtime.sendMessage({
    type: "grab",
    action: kind === "save" || kind === "savegif" ? "save" : "copy",
    gif: kind.endsWith("gif"),
    found,
  }, (res) => {
    if (res && res.ok) {
      setStatus(res.action === "copy" ? "Copied — ⌘V to paste" : `Saved ${res.path}`, "ok");
      setTimeout(() => window.close(), 1200);
    } else {
      setStatus((res && res.error) || "Failed", "err");
      for (const b of document.querySelectorAll("button")) b.disabled = false;
    }
  });
});

init();
