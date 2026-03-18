// CryptoMind Service Worker — enables PWA install prompt
const CACHE_NAME = "cryptomind-v1";

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(clients.claim());
});

self.addEventListener("fetch", (e) => {
  // Network-first strategy — always try live data
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
