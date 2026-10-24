// Locus Service Worker for PWA
const CACHE_NAME = 'locus-v1';
const PRECACHE_URLS = [
  '/',
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch(() => {
        // precache failure shouldn't block install
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Network-first for static assets with cache fallback.
  // no-store bypasses the browser HTTP cache so a PWA never sticks to stale JS/CSS.
  if (event.request.method === 'GET' && event.request.url.includes('/static/')) {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' }).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        return caches.match(event.request, { ignoreSearch: true });
      })
    );
  }
});
