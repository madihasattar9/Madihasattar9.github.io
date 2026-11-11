// Minimal service worker: makes the app installable and able to receive shares.
// It deliberately caches nothing yet, so updates always arrive.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
