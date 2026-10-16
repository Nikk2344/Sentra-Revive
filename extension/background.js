const API = "http://127.0.0.1:8765/event";

function send(type, tab) {
  if (!tab || !tab.url || !/^https?:/.test(tab.url) || tab.incognito) return;
  fetch(API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, url: tab.url, title: tab.title || "", ts: Date.now() / 1000 }),
  }).catch(() => {}); // companion offline: drop silently
}

chrome.tabs.onActivated.addListener(({ tabId }) => chrome.tabs.get(tabId, (t) => send("tab_activated", t)));

chrome.tabs.onUpdated.addListener((_id, info, tab) => {
  if (info.status === "complete") {
    const q = /[?&](q|query|search_query)=/.test(tab.url || "");
    send(q ? "search" : "navigated", tab);
  }
});
