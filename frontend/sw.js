/* =========================
   Service Worker — App Shell + Offline Support
   Cache-first for static assets, network-first for API
   ========================= */

const CACHE_VERSION = 'v2';
const CACHE_NAME = 'call-sched-' + CACHE_VERSION;
const STATIC_CACHE = 'call-sched-static-' + CACHE_VERSION;
const OFFLINE_URL = '/offline.html';

const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/style.css',
  '/js/theme.js',
  '/js/storage.js',
  '/js/api.js',
  '/js/calendar.js',
  '/js/doctor_config.js',
  '/js/auth.js',
  '/js/app.js',
  '/icons/icon-72.png',
  '/icons/icon-96.png',
  '/icons/icon-128.png',
  '/icons/icon-144.png',
  '/icons/icon-152.png',
  '/icons/icon-192.png',
  '/icons/icon-384.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-192.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/offline.html',
];

// ── Install — precache app shell ─────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => {
        console.log('[SW] Precaching app shell');
        return cache.addAll(PRECACHE_URLS.map(url => {
          const fullUrl = self.location.origin + url;
          return new Request(fullUrl, { cache: 'reload' });
        })).catch(err => {
          console.warn('[SW] Some URLs failed to precache:', err);
        });
      })
      .then(() => self.skipWaiting())
  );
});

// ── Activate — clean old caches ──────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(key => key !== CACHE_NAME && key !== STATIC_CACHE)
          .map(key => {
            console.log('[SW] Deleting old cache:', key);
            return caches.delete(key);
          })
      ))
      .then(() => {
        console.log('[SW] Activated');
        return self.clients.claim();
      })
  );
});

// ── Fetch — route-based strategy ─────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Skip non-GET requests
  if (event.request.method !== 'GET') return;

  // Skip Chrome extensions and devtools
  if (url.protocol === 'chrome-extension:') return;

  // API calls — network first, queue if offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Static assets — cache first, fall back to network
  if (
    url.pathname.match(/\.(js|css|png|jpg|jpeg|svg|ico|woff2?|ttf|eot|webp)$/) ||
    url.pathname.startsWith('/icons/') ||
    url.pathname.startsWith('/js/') ||
    url.pathname.startsWith('/css/')
  ) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // HTML pages — network first, fall back to cache, then offline page
  if (event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirstForHTML(event.request));
    return;
  }

  // Default — network first
  event.respondWith(networkFirst(event.request));
});

// ── Cache strategies ──────────────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    console.warn('[SW] cacheFirst fallback for:', request.url);
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) {
      console.log('[SW] Network failed, serving cached:', request.url);
      return cached;
    }
    // Return a JSON error response for API calls when offline
    if (request.url.includes('/api/')) {
      return new Response(
        JSON.stringify({ error: 'Offline', offline: true }),
        { status: 503, headers: { 'Content-Type': 'application/json' } }
      );
    }
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirstForHTML(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;

    // Try to serve offline.html
    try {
      const offlinePage = await caches.match(self.location.origin + OFFLINE_URL);
      if (offlinePage) return offlinePage;
    } catch (e) {}

    return new Response('Offline', { status: 503 });
  }
}

// ── Background Sync — replay queued API calls ─────────────────────────────────
self.addEventListener('sync', event => {
  if (event.tag === 'sync-api-queue') {
    event.waitUntil(replayQueuedRequests());
  }
});

async function replayQueuedRequests() {
  const cache = await caches.open(CACHE_NAME);
  const keys = await cache.keys();
  for (const request of keys) {
    if (request.headers.get('X-Queued-Request')) {
      console.log('[SW] Replaying queued request:', request.url);
      try {
        await fetch(request.clone());
        cache.delete(request);
      } catch (err) {
        console.warn('[SW] Replay failed for:', request.url);
      }
    }
  }
}