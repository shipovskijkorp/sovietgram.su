/* Cache only the public, account-independent offline shell. Never cache
   authenticated HTML, API responses, messages, avatars or attachments. */
"use strict";
const CACHE = "sovietgram-public-shell-v1";
const PUBLIC = ["/offline/", "/app-icon/192.png", "/app-icon/512.png"];

let shellLoad = null;
function populateShell() {
  if (shellLoad) return shellLoad;
  shellLoad = (async () => {
    // Download all public assets before opening the cache, so a failed
    // offline attempt doesn't leave an empty cache marked as initialized.
    const responses = await Promise.all(PUBLIC.map(async path => {
      const response = await fetch(path, {credentials:"omit", cache:"reload", redirect:"error"});
      if (!response.ok) throw new Error("Offline shell unavailable");
      return [path, response];
    }));
    const cache = await caches.open(CACHE);
    try {
      for (const [path, response] of responses) await cache.put(path, response);
    } catch (error) {
      await caches.delete(CACHE);
      throw error;
    }
  })().finally(() => { shellLoad = null; });
  return shellLoad;
}

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    await populateShell();
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith("sovietgram-public-shell-") && key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (!url.search && PUBLIC.includes(url.pathname)) {
    event.respondWith(fetch(request).catch(async () => (await caches.match(url.pathname)) || Response.error()));
    return;
  }
  if (request.mode === "navigate" && !url.pathname.startsWith("/admin/") && !url.pathname.startsWith("/control/")) {
    const network = fetch(request);
    event.respondWith(network.catch(async () => (await caches.match("/offline/")) || Response.error()));
    // Restore the public offline shell after a deliberate cache clear,
    // without delaying the successful page response or caching private HTML.
    event.waitUntil(network.then(async response => {
      if (response.ok && !(await caches.has(CACHE))) await populateShell();
    }).catch(() => {}));
  }
});
