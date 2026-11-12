// عمل بلا إنترنت لغرفة الإعلام. غيّر VERSION عند تعديل أي ملف.
// يخدم فقط ملفات المجلد الرئيسي؛ تطبيقا «نصيب» و«الشكاوى» في مجلداتهما لا يتأثران.
const VERSION = 'media-room-v4';
const CORE = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/maskable-512.png', 'icons/apple-touch-icon.png'];
const FONT_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith('media-room-') && k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const scopePath = new URL(self.registration.scope).pathname;
// ملف في المجلد الرئيسي نفسه (مش داخل مجلد فرعي)، أو مجلد icons
function isOwn(url) {
  if (url.origin !== location.origin || !url.pathname.startsWith(scopePath)) return false;
  const rest = url.pathname.slice(scopePath.length);
  return !rest.includes('/') || rest.startsWith('icons/');
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (isOwn(url)) {
    // الشبكة أولًا حتى توصل التحديثات، والنسخة المحفوظة إذا ما في إنترنت
    const key = req.mode === 'navigate' ? 'index.html' : req;
    e.respondWith(fetch(req).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(key, copy)); }
      return r;
    }).catch(() => caches.match(key, { ignoreSearch: true })));
    return;
  }
  if (FONT_HOSTS.includes(url.hostname)) {
    // الخطوط: من المحفوظ أولًا، حتى تطلع التصاميم بنفس الخط بلا إنترنت
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(r => {
      const copy = r.clone(); caches.open(VERSION).then(c => c.put(req, copy)); return r;
    })));
  }
});
