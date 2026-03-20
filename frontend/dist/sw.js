// CryptoMind Service Worker — self-cleaning
// Unregisters itself and clears all caches to prevent stale asset issues

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  // Clear ALL caches
  e.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.map((name) => caches.delete(name)))
    ).then(() => {
      // Unregister this service worker
      return self.registration.unregister();
    }).then(() => {
      // Take over all clients and force refresh
      return self.clients.claim();
    })
  );
});

// No fetch handler — let everything go to network directly
