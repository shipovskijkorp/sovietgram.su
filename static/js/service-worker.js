/* Cache only the public, account-independent offline shell. Never cache
   authenticated HTML, API responses, messages, avatars or attachments. */
"use strict";
const CACHE = "sovietgram-public-shell-v1";
const PUBLIC = ["/offline/", "/app-icon/192.png", "/app-icon/512.png"];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    for (const path of PUBLIC) {
      const response = await fetch(path, {credentials:"omit", cache:"reload", redirect:"error"});
      if (!response.ok) throw new Error("Offline shell unavailable");
      await cache.put(path, response);
    }
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
    event.respondWith(fetch(request).catch(async () => (await caches.match("/offline/")) || Response.error()));
  }
});
