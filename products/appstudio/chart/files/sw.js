// Served at /sw.js in place of opencode's service worker, whose navigation
// fallback answers every page with opencode's own, the chrome's included. This
// one takes its place, drops its caches and handles no requests.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});
