// طلبيّة: كاش للعمل بلا إنترنت + استقبال الفويس من «مشاركة» بواتساب (أندرويد)
const VERSION = 'talabiye-v1';
const CORE = ['./', 'index.html', 'app.html', 'pin.html', 'style.css', 'config.js', 'manifest.webmanifest', 'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== VERSION && k !== 'talabiye-share').map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  const url = new URL(req.url);

  // share_target: الملف بيوصل POST، منحطو بالكاش ومنفتح التطبيق
  if (req.method === 'POST' && url.pathname.endsWith('/share')) {
    e.respondWith((async () => {
      const form = await req.formData();
      const file = form.get('audio');
      if (file && typeof file !== 'string') {
        const c = await caches.open('talabiye-share');
        await c.put('shared-file', new Response(file, { headers: { 'content-type': file.type || 'audio/ogg', 'x-name': encodeURIComponent(file.name || 'voice.opus') } }));
      }
      return Response.redirect('app.html?shared=1', 303);
    })());
    return;
  }

  if (req.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(fetch(req).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(req, copy)); }
    return r;
  }).catch(() => caches.match(req, { ignoreSearch: true })));
});
