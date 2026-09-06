/* ICON TRACE - service worker.
 *
 * DELIBERATE offline, replacing the accidental kind.
 *
 * The browser used to cache the page on its own judgement: a stale screen
 * would load with the server stopped, the chip would say Online, and nothing
 * was saved. Everything is now sent `no-store`, so that cannot happen again.
 *
 * The Cache API is separate from the HTTP cache, so this worker can still
 * store what it is explicitly told to. That is the difference - the shell is
 * cached because we decided to cache it, under a name that carries the build,
 * and every old cache is deleted the moment a new build activates. A stale
 * screen cannot survive a deploy.
 *
 * SCOPE, as agreed: FQC and Packing work offline. Challan and Gate Pass do
 * NOT - both draw a document number from a transactional counter, and a
 * number invented in a browser is a number that can collide.
 *
 * REQUIRES HTTPS OR LOCALHOST. Service workers refuse to register over plain
 * HTTP, silently. On the plant LAN that means offline mode does nothing until
 * the certificate work is done - so the app checks and says so rather than
 * pretending.
 */

const BUILD = new URL(self.location).searchParams.get('b') || 'dev';
const SHELL = 'icon-shell-' + BUILD;

/* Only what a screen needs to render. Never an API response - stale data
   presented as current is the failure this whole system exists to prevent. */
const SHELL_URLS = [
  '/',
  '/static/icon_table.js?b=' + BUILD,
  '/static/icon_live.js?b=' + BUILD,
  '/static/icon_offline.js?b=' + BUILD,
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL)
      .then((c) => Promise.allSettled(SHELL_URLS.map((u) => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith('icon-shell-') && k !== SHELL)
            .map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;                 // writes are the outbox's job

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  /* API reads are never served from cache. A number on screen must either be
     current or absent - never last week's, quietly. */
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;

  /* Network first, cache only as a fallback, so a running server always wins
     and the cached copy is genuinely a last resort. */
  e.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(SHELL).then((c) => c.put(req, copy)).catch(() => {});
        }
        return resp;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('/')))
  );
});

self.addEventListener('message', (e) => {
  if (e.data === 'skipWaiting') self.skipWaiting();
});
