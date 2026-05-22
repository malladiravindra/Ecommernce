const CACHE_NAME = 'shopping-app-v1';
const URLS_TO_CACHE = [
  '/',
  '/static/css/style.css',
  '/static/manifest.json',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

// Install event: cache core assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened cache');
        return cache.addAll(URLS_TO_CACHE);
      })
  );
  self.skipWaiting();
});

// Fetch event: Network-first strategy
self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request).catch(() => {
      // If network fails, return from cache
      return caches.match(event.request);
    })
  );
});

// Activate event: clean up old caches
self.addEventListener('activate', event => {
  const cacheWhitelist = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});
