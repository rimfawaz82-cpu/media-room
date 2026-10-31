import { loadCatalog } from './catalog.js';
import { createStudio } from './scene.js';

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const lum = (hex) => { const n = parseInt(String(hex).slice(1).padEnd(6, '0'), 16); return (0.2126 * (n >> 16) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255; };
const DESIGN_KEY = 'cupstudio.design.v1';
const ORDERS_KEY = 'cupstudio.orders.v1';

const cat = await loadCatalog();
const byId = (list, id) => list.find((x) => x.id === id) || list[0];
const cur = cat.shop.currency || '$';
const money = (n) => `${Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })}${cur}`;

$('#shopName').textContent = cat.shop.name; $('#shopTag').textContent = cat.shop.tagline;
document.title = `${cat.shop.name} · صمّم هديتك`;

// ---------- الحالة ----------
const occ0 = cat.occasions[0];
const defaults = {
  step: 0, occasion: occ0?.id, to: '',
  cup: cat.cups[0].id, cupColor: occ0?.cup || cat.cupColors[0].hex,
  text: occ0?.text || '', line2: '', font: occ0?.font || cat.fonts[0].id, textColor: '#c2405a',
  deco: occ0?.pattern || 'none', sticker: 'heart',
  box: (cat.boxes.find((b) => b.id === 'm') || cat.boxes[1] || cat.boxes[0]).id,
  boxColor: occ0?.box || cat.boxColors[0].hex, ribbon: 'gold',
  addons: [], message: '',
  name: '', phone: '', address: '', date: '',
};
let S = { ...defaults };
try { const saved = JSON.parse(localStorage.getItem(DESIGN_KEY) || 'null'); if (saved) S = { ...defaults, ...saved }; } catch (e) {}
const save = () => { try { localStorage.setItem(DESIGN_KEY, JSON.stringify(S)); } catch (e) {} };

const STEPS = ['المناسبة', 'الكوب', 'لمستك', 'البوكس', 'الإضافات', 'الطلب'];

// ---------- الأسعار ----------
function lines() {
  const cup = byId(cat.cups, S.cup), deco = byId(cat.decorations, S.deco), st = byId(cat.stickers, S.sticker);
  const box = byId(cat.boxes, S.box), rib = byId(cat.ribbons, S.ribbon);
  const L = [[`${cup.name}`, +cup.price]];
  if (+deco.price) L.push([`زخرفة: ${deco.name}`, +deco.price]);
  if (+st.price) L.push([`ملصق: ${st.name}`, +st.price]);
  if (box.w) {
    L.push([`بوكس ${box.name}`, +box.price]);
    if (+rib.price) L.push([`شريطة ${rib.name}`, +rib.price]);
    S.addons.forEach((id) => { const a = cat.addons.find((x) => x.id === id); if (a) L.push([a.name, +a.price]); });
  }
  if (+cat.shop.delivery) L.push(['توصيل', +cat.shop.delivery]);
  return L;
}
const total = () => lines().reduce((s, l) => s + l[1], 0);
let shownTotal = 0;
function renderTotal() {
  const t = total(), el = $('#total');
  if (t !== shownTotal) { el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump'); }
  const from = shownTotal, start = performance.now();
  shownTotal = t;
  const step = (now) => { const k = Math.min(1, (now - start) / 350); el.textContent = money(Math.round(from + (t - from) * k)); if (k < 1) requestAnimationFrame(step); else el.textContent = money(t); };
  requestAnimationFrame(step);
}

// ---------- 3D ----------
const studio = createStudio($('#three'));
const fontCss = (id) => byId(cat.fonts, id).css;
function sync3D() {
  const deco = byId(cat.decorations, S.deco), st = byId(cat.stickers, S.sticker);
  const box = byId(cat.boxes, S.box), rib = byId(cat.ribbons, S.ribbon);
  studio.setCup({
    shape: byId(cat.cups, S.cup).shape, color: S.cupColor, text: S.text, line2: S.line2,
    font: fontCss(S.font), textColor: S.textColor, pattern: deco.pattern, patternImg: deco.img || '',
    sticker: st.emoji || '', stickerImg: st.img || '', backText: cat.shop.name,
  });
  studio.setBox(box.w ? {
    w: +box.w, h: +box.h, d: +box.d, color: S.boxColor, ribbon: rib.hex || '',
    to: S.to.trim(), shopName: cat.shop.name, message: S.message || S.text,
    addons: S.addons.map((id) => cat.addons.find((a) => a.id === id)).filter(Boolean).map((a) => ({ id: a.id, kind: a.kind })),
  } : { w: 0 });
  document.querySelectorAll('.seg button').forEach((b) => { if (b.dataset.view !== 'cup') b.disabled = !box.w; });
  renderTotal(); save();
}
let syncT = 0;
const sync3DSoon = () => { clearTimeout(syncT); syncT = setTimeout(sync3D, 60); };

function setView(v) {
  if (v !== 'cup' && !byId(cat.boxes, S.box).w) v = 'cup';
  studio.setView(v);
  document.querySelectorAll('.seg button').forEach((b) => b.classList.toggle('on', b.dataset.view === v));
}
const viewForStep = (s) => (s <= 2 ? 'cup' : s === 5 ? 'gift' : 'box');

// ---------- أشكال صغيرة للأكواب ----------
const SHAPE_SVG = {
  mug: '<path d="M14 14h24v26a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4z"/><path d="M38 20h4a6 6 0 0 1 0 12h-4"/>',
  latte: '<path d="M10 16h32l-4 24a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4z"/><path d="M41 22h3a5 5 0 0 1 0 10h-5"/>',
  travel: '<rect x="15" y="8" width="22" height="6" rx="2"/><path d="M16 14h20l-2 30H18z"/>',
  glass: '<path d="M14 10h24l-2 32a3 3 0 0 1-3 3H19a3 3 0 0 1-3-3z"/><path d="M16 22h20" opacity=".5"/>',
};
const shapeSvg = (s) => `<svg class="shape" viewBox="0 0 54 54" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round">${SHAPE_SVG[s] || SHAPE_SVG.mug}</svg>`;
const priceTag = (p) => (+p ? `<span class="price">+${money(p)}</span>` : '<small>مجاناً</small>');
const swatches = (key, list, extra = '') => `<div class="swatches">${list.map((c) => {
  const hex = typeof c === 'string' ? c : c.hex, name = typeof c === 'string' ? hex : c.name;
  return `<button class="sw ${S[key] === hex ? 'on' : ''}" style="background:${esc(hex)}" data-set="${key}" data-val="${esc(hex)}" title="${esc(name)}" aria-label="${esc(name)}"></button>`;
}).join('')}${extra}</div>`;
const pick = (key, item, inner, cls = '') => `<button class="opt ${cls} ${S[key] === item.id ? 'on' : ''}" data-set="${key}" data-val="${esc(item.id)}">${item.badge ? `<span class="badge">${esc(item.badge)}</span>` : ''}${inner}</button>`;

// ---------- الخطوات ----------
const views = {
  0: () => `
    <h1 class="h">لمين هالهدية؟ 💝</h1>
    <p class="sub">اختار المناسبة ومنجهّزلك تصميم بيليق فيها، وبعدين بتغيّر يلي بدك ياه.</p>
    <div class="group"><div class="grid g3">${cat.occasions.map((o) => pick('occasion', o, `<span class="emo">${o.emoji}</span><b>${esc(o.name)}</b>`)).join('')}</div></div>
    <div class="group"><label for="to">شو اسم يلي رح ياخدها؟ <small>اختياري</small></label>
      <input class="field" id="to" data-input="to" maxlength="18" placeholder="مثلاً: سارة" value="${esc(S.to)}" autocomplete="off">
    </div>
    <div class="tip">✨ الاسم بينكتب على الكوب وعلى البوكس — الهدية يلي فيها اسم بتنحفظ بالقلب أكتر.</div>`,

  1: () => `
    <h1 class="h">اختار كوبك ☕</h1>
    <p class="sub">لفّو بإيدك وشوفو من كل الجهات.</p>
    <div class="group"><div class="grid g2">${cat.cups.map((c) => pick('cup', c, `${shapeSvg(c.shape)}<b>${esc(c.name)}</b><small>${esc(c.desc)}</small><span class="price">${money(c.price)}</span>`)).join('')}</div></div>
    <div class="group"><div class="glabel">لون الكوب <small>${esc((cat.cupColors.find((c) => c.hex === S.cupColor) || {}).name || '')}</small></div>${swatches('cupColor', cat.cupColors)}</div>`,

  2: () => `
    <h1 class="h">حط لمستك 🖋️</h1>
    <p class="sub">كلمة صغيرة بتعمل فرق كبير.</p>
    <div class="group"><label for="text">الكتابة الرئيسية <span class="counter" id="c-text">${S.text.length}/22</span></label>
      <input class="field" id="text" data-input="text" maxlength="22" value="${esc(S.text)}" placeholder="اسم أو كلمة" autocomplete="off"></div>
    <div class="group"><label for="line2">سطر صغير تحتها <small>تاريخ، جملة…</small></label>
      <input class="field" id="line2" data-input="line2" maxlength="30" value="${esc(S.line2)}" placeholder="مثلاً: ١٤ شباط ٢٠٢٦" autocomplete="off"></div>
    <div class="group fonts"><div class="glabel">نوع الخط</div><div class="grid g4">${cat.fonts.map((f) => pick('font', f, `<b style="font-family:${esc(f.css)}">${esc(S.text.trim().split(' ')[0] || 'أحبك')}</b><small>${esc(f.name)}</small>`)).join('')}</div></div>
    <div class="group"><div class="glabel">لون الكتابة</div>${swatches('textColor', cat.textColors)}</div>
    <div class="group"><div class="glabel">الزخرفة</div><div class="grid g4">${cat.decorations.map((d) => pick('deco', d, `${d.img ? `<img src="${esc(d.img)}" alt="" width="34" height="34" style="object-fit:cover;border-radius:8px">` : `<span class="emo" style="color:var(--rose)">${esc(d.emoji)}</span>`}<b>${esc(d.name)}</b>${priceTag(d.price)}`)).join('')}</div></div>
    <div class="group"><div class="glabel">ملصق</div><div class="grid g4">${cat.stickers.map((s) => pick('sticker', s, `${s.img ? `<img src="${esc(s.img)}" alt="" width="34" height="34" style="object-fit:contain">` : `<span class="emo">${s.emoji || '∅'}</span>`}<b>${esc(s.name)}</b>${priceTag(s.price)}`)).join('')}</div></div>`,

  3: () => {
    const box = byId(cat.boxes, S.box);
    return `
    <h1 class="h">غلّفها بحب 🎁</h1>
    <p class="sub">البوكس هو أول شي بيشوفو — خلّي أول لحظة تكون حلوة.</p>
    <div class="group"><div class="grid g2">${cat.boxes.map((b) => pick('box', b, `<span class="emo">${b.w ? '📦' : '☕'}</span><b>${esc(b.name)}</b><small>${esc(b.desc)}${b.w ? ` · ${b.w}×${b.d}×${b.h} سم` : ''}</small>${b.w ? `<span class="price">+${money(b.price)}</span>` : ''}`)).join('')}</div></div>
    ${box.w ? `
    <div class="group"><div class="glabel">لون البوكس</div>${swatches('boxColor', cat.boxColors)}</div>
    <div class="group"><div class="glabel">الشريطة</div><div class="grid g3">${cat.ribbons.map((r) => pick('ribbon', r, `<span class="sw ${r.hex ? '' : 'none'}" style="width:26px;height:26px;background:${esc(r.hex || '#fff')}"></span><b>${esc(r.name)}</b>${priceTag(r.price)}`)).join('')}</div></div>` : ''}`;
  },

  4: () => {
    const box = byId(cat.boxes, S.box);
    if (!box.w) return `<h1 class="h">الإضافات 🍫</h1><p class="sub">الإضافات بتنحط جوّا البوكس. ارجع اختار بوكس إذا حابب تضيف شوكولا، ورد، أو كرت.</p>
      <button class="btn gold" data-go="3">اختار بوكس</button>`;
    const hasCard = S.addons.some((id) => (cat.addons.find((a) => a.id === id) || {}).kind === 'card');
    return `
    <h1 class="h">زيد الفرحة 🍫🌹</h1>
    <p class="sub">كل إضافة بتطلع جوّا البوكس قدامك.</p>
    <div class="group"><div class="grid g2">${cat.addons.map((a) => `
      <button class="opt row ${S.addons.includes(a.id) ? 'on' : ''}" data-toggle="${esc(a.id)}">
        ${a.img ? `<img src="${esc(a.img)}" alt="" width="36" height="36" style="object-fit:contain">` : `<span class="emo">${a.emoji}</span>`}
        <span class="meta"><b>${esc(a.name)}</b><span class="price">+${money(a.price)}</span></span><span class="check">✓</span>
      </button>`).join('')}</div></div>
    ${hasCard ? `<div class="group"><label for="msg">شو بدك تكتب بالكرت؟ <span class="counter" id="c-message">${S.message.length}/120</span></label>
      <textarea class="field" id="msg" data-input="message" maxlength="120" placeholder="اكتب من قلبك…">${esc(S.message)}</textarea></div>` : '<div class="tip">💌 الكرت المكتوب بخط اليد هو أكتر شي بيضل محفوظ بعد ما تخلص القهوة.</div>'}`;
  },

  5: () => `
    <h1 class="h">هديتك جاهزة ✨</h1>
    <p class="sub">هيك رح تشوفها لحظة ما تفتحها.</p>
    ${byId(cat.boxes, S.box).w ? '<button class="btn gold reveal" id="reveal">🎁 افتح الهدية</button>' : ''}
    <div class="summary">${lines().map(([n, p]) => `<div class="ln"><span>${esc(n)}</span><span>${money(p)}</span></div>`).join('')}<div class="ln"><span>المجموع</span><span>${money(total())}</span></div></div>
    <div class="group"><div class="glabel">لوين منبعتها؟</div>
      <div class="grid" style="gap:10px">
        <div class="two"><input class="field" data-input="name" placeholder="اسمك" value="${esc(S.name)}" autocomplete="name">
        <input class="field" data-input="phone" placeholder="رقم الموبايل" inputmode="tel" value="${esc(S.phone)}" autocomplete="tel" dir="ltr" style="text-align:right"></div>
        <input class="field" data-input="address" placeholder="العنوان" value="${esc(S.address)}" autocomplete="street-address">
        <label class="glabel" style="margin:4px 0 -4px">بأي يوم بدك توصل؟</label>
        <input class="field" type="date" data-input="date" value="${esc(S.date)}">
      </div></div>`,
};

function renderSteps() {
  $('#steps').innerHTML = STEPS.map((n, i) => `<li class="${i < S.step ? 'done' : ''} ${i === S.step ? 'on' : ''}"><button data-go="${i}" aria-label="${n}"><span class="bar-line"><i></i></span><span class="lbl">${n}</span></button></li>`).join('');
  $('#prev').hidden = S.step === 0;
  const last = S.step === STEPS.length - 1;
  $('#next').textContent = last ? 'اطلب عبر واتساب' : S.step === 0 ? 'يلا نبلّش' : 'التالي';
  $('#next').classList.toggle('wa', last);
}
function render(keepScroll) {
  const body = $('#stepBody'), top = body.scrollTop;
  body.innerHTML = views[S.step]();
  if (keepScroll) { body.scrollTop = top; body.querySelectorAll('*').forEach((el) => (el.style.animation = 'none')); }
  renderSteps();
}
function go(step) {
  S.step = Math.max(0, Math.min(STEPS.length - 1, step));
  render(); setView(viewForStep(S.step)); save();
  $('#stepBody').scrollTop = 0;
  if (window.innerWidth <= 900) window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---------- التفاعل ----------
function applyOccasion(id) {
  const o = cat.occasions.find((x) => x.id === id); if (!o) return;
  Object.assign(S, { occasion: id, cupColor: o.cup || S.cupColor, boxColor: o.box || S.boxColor, deco: cat.decorations.some((d) => d.id === o.pattern) ? o.pattern : S.deco, font: o.font || S.font });
  const rib = cat.ribbons.find((r) => r.hex && r.hex.toLowerCase() === (o.ribbon || '').toLowerCase()); if (rib) S.ribbon = rib.id;
  // كتابة واضحة دايماً: على كوب فاتح منستعمل لون البوكس الغامق، وعلى كوب غامق الذهبي أو الأبيض
  if (lum(S.cupColor) > 0.5) S.textColor = o.box && lum(o.box) < 0.55 ? o.box : '#2b2b2b';
  else S.textColor = o.ribbon && lum(o.ribbon) > 0.4 ? o.ribbon : '#ffffff';
  if (S.to.trim()) { S.text = S.to.trim(); S.line2 = o.text; } else { S.text = o.text; S.line2 = ''; }
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('[data-set],[data-toggle],[data-go],[data-view],#reveal');
  if (!t) return;
  if (t.dataset.view) { setView(t.dataset.view); return; }
  if (t.dataset.go != null) { go(+t.dataset.go); return; }
  if (t.id === 'reveal') { reveal(); return; }
  if (t.dataset.toggle) {
    const id = t.dataset.toggle;
    S.addons = S.addons.includes(id) ? S.addons.filter((x) => x !== id) : [...S.addons, id];
    if (S.addons.includes(id)) setView('box');
  } else {
    const key = t.dataset.set, val = t.dataset.val;
    if (key === 'occasion') applyOccasion(val); else S[key] = val;
    if (key === 'box') setTimeout(() => setView(byId(cat.boxes, val).w ? 'box' : 'cup'), 30);
  }
  render(true); sync3D();
});

document.addEventListener('input', (e) => {
  const k = e.target.dataset.input; if (!k) return;
  S[k] = e.target.value;
  if (k === 'to') { const o = cat.occasions.find((x) => x.id === S.occasion); if (S.to.trim()) { S.text = S.to.trim(); S.line2 = o ? o.text : S.line2; } else if (o) { S.text = o.text; S.line2 = ''; } }
  const c = $('#c-' + k); if (c) c.textContent = `${S[k].length}/${e.target.maxLength}`;
  if (['text', 'line2', 'to', 'message'].includes(k)) sync3DSoon(); else save();
});

$('#prev').onclick = () => go(S.step - 1);
$('#next').onclick = () => (S.step === STEPS.length - 1 ? order() : go(S.step + 1));
if (window.top !== window) $('#snap').hidden = true;   // جوّا إطار المعاينة التحميل ممنوع
$('#snap').onclick = () => {
  const a = document.createElement('a'); a.href = studio.snapshot(); a.download = `${cat.shop.name}-تصميمي.png`; a.click();
  toast('📸 انحفظت صورة تصميمك');
};

function toast(msg) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('on');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('on'), 2600);
}
function confetti() {
  const box = $('#confetti'), colors = ['#c2405a', '#c9a14a', '#f6d5dc', '#7c9a83', '#f2a541', '#fff'];
  for (let i = 0; i < 90; i++) {
    const p = document.createElement('i');
    p.style.left = Math.random() * 100 + 'vw'; p.style.background = colors[i % colors.length];
    p.style.setProperty('--dx', (Math.random() - 0.5) * 200 + 'px'); p.style.setProperty('--r', Math.random() * 900 + 'deg');
    p.style.animationDuration = 1.8 + Math.random() * 1.6 + 's'; p.style.animationDelay = Math.random() * 0.3 + 's';
    box.appendChild(p); setTimeout(() => p.remove(), 4000);
  }
}
function reveal() {
  setView('gift'); studio.closeGift();
  setTimeout(() => { studio.openGift(); confetti(); toast(S.to.trim() ? `🥹 تخيّل وج ${S.to.trim()} هلق` : '🥹 هيك رح تكون اللحظة'); }, 900);
}

function order() {
  if (!S.name.trim() || !S.phone.trim()) { toast('بس اسمك ورقمك لنقدر نتواصل معك 🙏'); $('[data-input="' + (!S.name.trim() ? 'name' : 'phone') + '"]').focus(); return; }
  const cup = byId(cat.cups, S.cup), box = byId(cat.boxes, S.box);
  const colorName = (list, hex) => (list.find((c) => c.hex === hex) || {}).name || hex;
  const msg = [
    `مرحبا ${cat.shop.name} 👋 بدي اطلب هالهدية:`, '',
    `☕ ${cup.name} — ${colorName(cat.cupColors, S.cupColor)}`,
    S.text && `✍️ الكتابة: ${S.text}${S.line2 ? ' / ' + S.line2 : ''} (خط ${byId(cat.fonts, S.font).name})`,
    `🎨 زخرفة: ${byId(cat.decorations, S.deco).name} · ملصق: ${byId(cat.stickers, S.sticker).name}`,
    box.w ? `📦 بوكس ${box.name} — ${colorName(cat.boxColors, S.boxColor)} · شريطة ${byId(cat.ribbons, S.ribbon).name}` : '📦 بدون بوكس',
    box.w && S.addons.length ? `🎁 إضافات: ${S.addons.map((id) => (cat.addons.find((a) => a.id === id) || {}).name).filter(Boolean).join('، ')}` : '',
    S.message && `💌 الكرت: ${S.message}`,
    S.to && `👤 الهدية لـ: ${S.to}`, '',
    `💰 المجموع: ${money(total())}`, '',
    `الاسم: ${S.name}`, `الموبايل: ${S.phone}`, S.address && `العنوان: ${S.address}`, S.date && `تاريخ التوصيل: ${S.date}`,
  ].filter((x) => x !== false && x != null && x !== undefined).join('\n');
  try {
    const orders = JSON.parse(localStorage.getItem(ORDERS_KEY) || '[]');
    orders.unshift({ at: new Date().toISOString(), total: total(), design: { ...S }, text: msg });
    localStorage.setItem(ORDERS_KEY, JSON.stringify(orders.slice(0, 200)));
  } catch (e) {}
  confetti();
  const url = `https://wa.me/${String(cat.shop.whatsapp).replace(/\D/g, '')}?text=${encodeURIComponent(msg)}`;
  // رابط حقيقي (بعض المتصفحات بتمنع window.open)
  let box = $('#waBox');
  if (!box) { box = document.createElement('div'); box.id = 'waBox'; box.className = 'group'; $('#stepBody').appendChild(box); }
  box.innerHTML = `<div class="tip">✅ طلبك جاهز. إذا ما انفتح الواتساب لحالو، اكبس هون:</div><a class="btn primary wa" style="display:block;text-align:center;text-decoration:none" href="${url}" target="_blank" rel="noopener">افتح واتساب وابعت الطلب</a>`;
  box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  try { window.open(url, '_blank'); } catch (e) {}
}

// ---------- البداية ----------
render(); sync3D(); setView(viewForStep(S.step));
document.fonts?.ready.then(() => { sync3D(); });
['El Messiri', 'Lalezar', 'Tajawal', 'Reem Kufi Fun'].forEach((f) => document.fonts?.load(`700 80px "${f}"`).then(sync3DSoon).catch(() => {}));
setTimeout(() => $('#loading').classList.add('gone'), 400);
setTimeout(() => $('#hint').classList.add('gone'), 5000);
$('#three').addEventListener('pointerdown', () => $('#hint').classList.add('gone'), { once: true });
