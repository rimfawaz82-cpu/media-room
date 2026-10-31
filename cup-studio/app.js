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
document.title = `${cat.shop.name} · استوديو الهدايا`;

// ---------- الحالة ----------
const occ0 = cat.occasions[0];
const defaults = {
  step: 0, occasion: occ0?.id, to: '',
  cup: cat.cups[0].id, cupColor: occ0?.cup || cat.cupColors[0].hex,
  text: occ0?.text || '', line2: '', font: occ0?.font || cat.fonts[0].id, textColor: '#c2405a', started: false,
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
const defaultBox = cat.boxes.find((b) => b.w) || null;
let introMode = true;
function sync3D() {
  const deco = byId(cat.decorations, S.deco), st = byId(cat.stickers, S.sticker);
  let box = byId(cat.boxes, S.box); const rib = byId(cat.ribbons, S.ribbon);
  if (introMode && !box.w && defaultBox) box = defaultBox;   // المقدّمة دايماً بتبلّش بهدية مسكّرة
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
  document.querySelectorAll('.seg button').forEach((b) => { if (b.dataset.view !== 'cup') b.disabled = !byId(cat.boxes, S.box).w; });
  renderTotal(); save();
}
let syncT = 0;
const sync3DSoon = () => { clearTimeout(syncT); syncT = setTimeout(sync3D, 60); };

const isMobile = () => window.innerWidth <= 900;
function updateOffset() {
  if (isMobile()) return studio.setOffset(0, introMode ? window.innerHeight * 0.2 : 0);
  studio.setOffset(introMode ? window.innerWidth * 0.24 : (430 + 48) / 2);
}
window.addEventListener('resize', () => { updateOffset(); placeInk(); });

function setView(v) {
  if (v !== 'cup' && !byId(cat.boxes, S.box).w) v = 'cup';
  studio.setView(v);
  document.querySelectorAll('.seg button').forEach((b) => b.classList.toggle('on', b.dataset.view === v));
  placeInk();
}
function placeInk() {
  const on = $('.seg button.on'), ink = $('.seg-ink'); if (!on || !ink) return;
  ink.style.left = on.offsetLeft + 'px'; ink.style.width = on.offsetWidth + 'px';
}
const viewForStep = (s) => (s <= 2 ? 'cup' : s === 5 ? 'gift' : 'box');

// ---------- رسومات صغيرة ----------
const SHAPE_SVG = {
  mug: '<path d="M14 14h24v26a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4z"/><path d="M38 20h4a6 6 0 0 1 0 12h-4"/><path d="M20 8c0 2 2 2 2 4M27 7c0 2 2 2 2 4" opacity=".55"/>',
  latte: '<path d="M10 16h32l-4 24a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4z"/><path d="M41 22h3a5 5 0 0 1 0 10h-5"/><path d="M22 9c0 2 2 2 2 4M29 8c0 2 2 2 2 4" opacity=".55"/>',
  travel: '<rect x="14" y="7" width="24" height="7" rx="2.5"/><path d="M16 14h20l-2 31H18z"/><path d="M17 24h18M17.6 33h16.8" opacity=".5"/>',
  glass: '<path d="M14 10h24l-2 32a3 3 0 0 1-3 3H19a3 3 0 0 1-3-3z"/><path d="M15.5 24h21" opacity=".5"/><path d="M20 16l2 4" opacity=".7"/>',
};
const shapeSvg = (s) => `<svg class="shape" viewBox="0 0 54 54" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">${SHAPE_SVG[s] || SHAPE_SVG.mug}</svg>`;
const ICONS = [
  '<path d="M12 21s-7-4.4-9.3-9C1 8.6 3 5 6.6 5c2 0 3.6 1.1 4.4 2.6h2C13.8 6.1 15.4 5 17.4 5 21 5 23 8.6 21.3 12 19 16.6 12 21 12 21z"/>',
  '<path d="M5 8h12v9a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17"/><path d="M9 2.5c0 1.5 1 1.5 1 3M13 2.5c0 1.5 1 1.5 1 3"/>',
  '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
  '<rect x="3" y="9" width="18" height="12" rx="1.5"/><path d="M2 6h20v3H2zM12 6v15"/><path d="M12 6C10 2 6 2.5 7 5c.5 1 3 1 5 1zM12 6c2-4 6-3.5 5-1-.5 1-3 1-5 1z"/>',
  '<path d="M12 3l2.4 5.3 5.6.6-4.2 3.8 1.2 5.6L12 15.5 7 18.3l1.2-5.6L4 8.9l5.6-.6z"/>',
  '<path d="M4 12l5 5L20 6"/>',
];
const icon = (i) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[i]}</svg>`;
const priceTag = (p) => (+p ? `<span class="price">+${money(p)}</span>` : '<small>مجاناً</small>');
const swatches = (key, list) => `<div class="swatches">${list.map((c) => {
  const hex = typeof c === 'string' ? c : c.hex, name = typeof c === 'string' ? hex : c.name;
  return `<button class="sw ${S[key] === hex ? 'on' : ''}" style="background-color:${esc(hex)}" data-set="${key}" data-val="${esc(hex)}" title="${esc(name)}" aria-label="${esc(name)}"></button>`;
}).join('')}</div>`;
const pick = (key, item, inner, cls = '') => `<button class="opt ${cls} ${S[key] === item.id ? 'on' : ''}" data-set="${key}" data-val="${esc(item.id)}">${item.badge ? `<span class="badge">${esc(item.badge)}</span>` : ''}${inner}</button>`;
const colorName = (list, hex) => (list.find((c) => c.hex === hex) || {}).name || '';

// ---------- الخطوات ----------
const STEP_TITLES = ['لمين الهدية؟', 'اختار كوبك', 'حطّ لمستك', 'غلّفها بحب', 'زيد الفرحة', 'هديتك جاهزة'];
const views = {
  0: () => `
    <h2 class="h">${STEP_TITLES[0]}</h2>
    <p class="sub">اختار المناسبة ومنجهّزلك تصميم بيليق فيها. بعدين بتغيّر كل شي على ذوقك.</p>
    <div class="group"><div class="grid g3">${cat.occasions.map((o) => pick('occasion', o, `<span class="emo">${o.emoji}</span><b>${esc(o.name)}</b>`)).join('')}</div></div>
    <div class="group"><label class="glabel" for="to">اسم يلي رح ياخدها <small>بينكتب عالكوب والبوكس</small></label>
      <input class="field name" id="to" data-input="to" maxlength="18" placeholder="سارة" value="${esc(S.to)}" autocomplete="off"></div>
    <div class="tip"><i>✦</i><span>الهدية يلي عليها اسم بتنحفظ أكتر من أي هدية تانية. جرّب اكتب الاسم وشوف الكوب.</span></div>`,

  1: () => `
    <h2 class="h">${STEP_TITLES[1]}</h2>
    <p class="sub">لفّو بإيدك وشوفو من كل الجهات.</p>
    <div class="group"><div class="grid g2">${cat.cups.map((c) => pick('cup', c, `${shapeSvg(c.shape)}<b>${esc(c.name)}</b><small>${esc(c.desc)}</small><span class="price">${money(c.price)}</span>`)).join('')}</div></div>
    <div class="group"><div class="glabel">لون الكوب <small>${esc(colorName(cat.cupColors, S.cupColor))}</small></div>${swatches('cupColor', cat.cupColors)}</div>`,

  2: () => `
    <h2 class="h">${STEP_TITLES[2]}</h2>
    <p class="sub">كلمة صغيرة بتعمل فرق كبير.</p>
    <div class="group"><label class="glabel" for="text">الكتابة <span class="counter" id="c-text">${S.text.length}/22</span></label>
      <input class="field name" id="text" data-input="text" maxlength="22" value="${esc(S.text)}" placeholder="اسم أو كلمة" autocomplete="off" style="font-family:${esc(fontCss(S.font))}"></div>
    <div class="group"><label class="glabel" for="line2">سطر صغير تحتها <small>تاريخ، جملة…</small></label>
      <input class="field" id="line2" data-input="line2" maxlength="30" value="${esc(S.line2)}" placeholder="١٤ شباط ٢٠٢٦" autocomplete="off"></div>
    <div class="group"><div class="glabel">الخط</div><div class="grid g3">${cat.fonts.map((f) => pick('font', f, `<b style="font-family:${esc(f.css)}">${esc(S.text.trim().split(' ')[0] || 'أحبك')}</b><small>${esc(f.name)}</small>`, 'fontopt')).join('')}</div></div>
    <div class="group"><div class="glabel">لون الكتابة</div>${swatches('textColor', cat.textColors)}</div>
    <div class="group"><div class="glabel">الزخرفة</div><div class="grid g3">${cat.decorations.map((d) => pick('deco', d, `${d.img ? `<img src="${esc(d.img)}" alt="" width="34" height="34" style="object-fit:cover;border-radius:8px">` : `<span class="emo" style="color:var(--blush)">${esc(d.emoji)}</span>`}<b>${esc(d.name)}</b>${priceTag(d.price)}`)).join('')}</div></div>
    <div class="group"><div class="glabel">ملصق بالنص</div><div class="grid g3">${cat.stickers.map((s) => pick('sticker', s, `${s.img ? `<img src="${esc(s.img)}" alt="" width="34" height="34" style="object-fit:contain">` : `<span class="emo">${s.emoji || '<span style="opacity:.4">∅</span>'}</span>`}<b>${esc(s.name)}</b>${priceTag(s.price)}`)).join('')}</div></div>`,

  3: () => {
    const box = byId(cat.boxes, S.box);
    return `
    <h2 class="h">${STEP_TITLES[3]}</h2>
    <p class="sub">البوكس هو أول لحظة. خلّيها تخطف القلب.</p>
    <div class="group"><div class="grid g2">${cat.boxes.map((b) => pick('box', b, `<span class="emo">${b.w ? '🎁' : '☕'}</span><b>${esc(b.name)}</b><small>${esc(b.desc)}${b.w ? `<br>${b.w}×${b.d}×${b.h} سم` : ''}</small>${b.w ? `<span class="price">+${money(b.price)}</span>` : ''}`)).join('')}</div></div>
    ${box.w ? `
    <div class="group"><div class="glabel">لون البوكس <small>${esc(colorName(cat.boxColors, S.boxColor))}</small></div>${swatches('boxColor', cat.boxColors)}</div>
    <div class="group"><div class="glabel">الشريطة</div><div class="grid g3">${cat.ribbons.map((r) => pick('ribbon', r, `<span class="sw mini ${r.hex ? '' : 'none'}" style="background-color:${esc(r.hex || 'transparent')}"></span><b>${esc(r.name)}</b>${priceTag(r.price)}`)).join('')}</div></div>` : ''}`;
  },

  4: () => {
    const box = byId(cat.boxes, S.box);
    if (!box.w) return `<h2 class="h">${STEP_TITLES[4]}</h2><p class="sub">الإضافات بتنحط جوّا البوكس. اختار بوكس لتضيف شوكولا، ورد، أو كرت.</p>
      <button class="btn gold" data-go="3">اختار بوكس</button>`;
    const hasCard = S.addons.some((id) => (cat.addons.find((a) => a.id === id) || {}).kind === 'card');
    return `
    <h2 class="h">${STEP_TITLES[4]}</h2>
    <p class="sub">كل إضافة بتوقع جوّا البوكس قدامك.</p>
    <div class="group"><div class="grid g2">${cat.addons.map((a) => `
      <button class="opt row ${S.addons.includes(a.id) ? 'on' : ''}" data-toggle="${esc(a.id)}">
        ${a.img ? `<img src="${esc(a.img)}" alt="" width="36" height="36" style="object-fit:contain">` : `<span class="emo">${a.emoji}</span>`}
        <span class="meta"><b>${esc(a.name)}</b><span class="price">+${money(a.price)}</span></span><span class="tick">✓</span>
      </button>`).join('')}</div></div>
    ${hasCard ? `<div class="group"><label class="glabel" for="msg">شو بدك تكتب بالكرت؟ <span class="counter" id="c-message">${S.message.length}/120</span></label>
      <textarea class="field" id="msg" data-input="message" maxlength="120" placeholder="اكتب من قلبك…">${esc(S.message)}</textarea></div>`
      : '<div class="tip"><i>✦</i><span>الكرت المكتوب بخط اليد بيضل محفوظ سنين بعد ما تخلص القهوة.</span></div>'}`;
  },

  5: () => `
    <h2 class="h">${STEP_TITLES[5]}</h2>
    <p class="sub">${S.to.trim() ? `هيك رح تشوفها ${esc(S.to.trim())} لحظة ما تفتحها.` : 'هيك رح تكون اللحظة.'}</p>
    ${byId(cat.boxes, S.box).w ? `<button class="btn ghost reveal" id="reveal">${icon(3)}<span>افتح الهدية</span></button>` : ''}
    <div class="summary">${lines().map(([n, p]) => `<div class="ln"><span>${esc(n)}</span><span>${money(p)}</span></div>`).join('')}<div class="ln total"><span>المجموع</span><span>${money(total())}</span></div></div>
    <div class="group"><div class="glabel">لوين منبعتها؟</div>
      <div class="stack">
        <div class="two"><input class="field" id="f-name" data-input="name" placeholder="اسمك" value="${esc(S.name)}" autocomplete="name">
        <input class="field" id="f-phone" data-input="phone" placeholder="رقم الموبايل" inputmode="tel" value="${esc(S.phone)}" autocomplete="tel" dir="ltr" style="text-align:right"></div>
        <input class="field" id="f-address" data-input="address" placeholder="العنوان" value="${esc(S.address)}" autocomplete="street-address">
        <label class="glabel" for="f-date" style="margin:6px 0 -2px">بأي يوم بدك توصل؟</label>
        <input class="field" id="f-date" type="date" data-input="date" value="${esc(S.date)}">
      </div></div>`,
};

const DOCK = ['المناسبة', 'الكوب', 'لمستك', 'البوكس', 'الإضافات', 'الطلب'];
const AR = (n) => String(n).replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[d]);
function renderChrome() {
  $('#dock').innerHTML = DOCK.map((n, i) => `<button data-go="${i}" class="${i === S.step ? 'on' : i < S.step ? 'done' : ''}" aria-label="${n}">${icon(i)}<span>${n}</span></button>`).join('');
  $('#stepNo').textContent = `الخطوة ${AR(S.step + 1)} من ${AR(DOCK.length)}`;
  $('#progress').style.width = ((S.step + 1) / DOCK.length) * 100 + '%';
  $('#prev').hidden = S.step === 0;
  const last = S.step === DOCK.length - 1;
  $('#next').textContent = last ? 'اطلب عبر واتساب' : S.step === 0 ? 'يلا نصمّم' : `التالي: ${DOCK[S.step + 1]}`;
  $('#next').classList.toggle('wa', last); $('#next').classList.toggle('gold', !last);
}
function render(keep) {
  const body = $('#stepBody'), top = body.scrollTop;
  body.classList.toggle('still', !!keep);
  body.innerHTML = views[S.step]();
  [...body.children].forEach((el, i) => el.style.setProperty('--i', i));
  if (keep) body.scrollTop = top;
  renderChrome();
}
function go(step) {
  S.step = Math.max(0, Math.min(DOCK.length - 1, step));
  render(); setView(viewForStep(S.step)); save();
  $('#stepBody').scrollTop = 0;
}

// ---------- التفاعل ----------
function applyOccasion(id) {
  const o = cat.occasions.find((x) => x.id === id); if (!o) return;
  Object.assign(S, { occasion: id, cupColor: o.cup || S.cupColor, boxColor: o.box || S.boxColor, deco: cat.decorations.some((d) => d.id === o.pattern) ? o.pattern : S.deco, font: cat.fonts.some((f) => f.id === o.font) ? o.font : S.font });
  const rib = cat.ribbons.find((r) => r.hex && r.hex.toLowerCase() === (o.ribbon || '').toLowerCase()); if (rib) S.ribbon = rib.id;
  // كتابة واضحة دايماً: على كوب فاتح لون البوكس الغامق، وعلى كوب غامق الذهبي أو الأبيض
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
    const id = t.dataset.toggle, adding = !S.addons.includes(id);
    S.addons = adding ? [...S.addons, id] : S.addons.filter((x) => x !== id);
    if (adding) setView('box');
  } else {
    const key = t.dataset.set, val = t.dataset.val;
    if (key === 'occasion') applyOccasion(val); else S[key] = val;
    if (key === 'box') setTimeout(() => setView(byId(cat.boxes, val).w ? 'box' : 'cup'), 30);
    if (['boxColor', 'ribbon'].includes(key) && studio.view === 'cup') setView('box');
  }
  render(true); sync3D(); studio.celebrate();
});

document.addEventListener('input', (e) => {
  const k = e.target.dataset.input; if (!k) return;
  S[k] = e.target.value;
  if (k === 'to') { const o = cat.occasions.find((x) => x.id === S.occasion); if (S.to.trim()) { S.text = S.to.trim(); S.line2 = o ? o.text : S.line2; } else if (o) { S.text = o.text; S.line2 = ''; } }
  if (k === 'text') document.querySelectorAll('.fontopt b').forEach((b) => (b.textContent = S.text.trim().split(' ')[0] || 'أحبك'));
  const c = $('#c-' + k); if (c) c.textContent = `${S[k].length}/${e.target.maxLength}`;
  if (['text', 'line2', 'to', 'message'].includes(k)) sync3DSoon(); else save();
});

// كبسة عالـ3D بتفتح الخطوة المناسبة
studio.on('pick', (what) => {
  if (introMode) return start();
  if (what === 'cup' && S.step !== 1 && S.step !== 2) { go(2); toast('عدّل كوبك من هون'); }
  else if (what === 'box' && S.step !== 3) { go(3); toast('عدّل البوكس والشريطة'); }
  else if (what === 'addon' && S.step !== 4) go(4);
  studio.celebrate();
});

$('#prev').onclick = () => go(S.step - 1);
$('#next').onclick = () => (S.step === DOCK.length - 1 ? order() : go(S.step + 1));
if (window.top !== window) $('#snap').hidden = true;   // جوّا إطار المعاينة التحميل ممنوع
$('#snap').onclick = () => {
  const a = document.createElement('a'); a.href = studio.snapshot(); a.download = `${cat.shop.name}-هديتي.png`; a.click();
  toast('انحفظت صورة هديتك');
};

function toast(msg) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('on');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('on'), 2600);
}
function confetti(n = 110) {
  const box = $('#confetti'), colors = ['#ec5d86', '#eebd6a', '#f7c5d4', '#fff0c4', '#b9832f', '#ffffff'];
  for (let i = 0; i < n; i++) {
    const p = document.createElement('i');
    p.style.left = Math.random() * 100 + 'vw'; p.style.background = colors[i % colors.length];
    p.style.setProperty('--dx', (Math.random() - 0.5) * 240 + 'px'); p.style.setProperty('--r', Math.random() * 900 + 'deg');
    p.style.animationDuration = 2 + Math.random() * 1.8 + 's'; p.style.animationDelay = Math.random() * 0.4 + 's';
    if (i % 3 === 0) p.style.borderRadius = '50%';
    box.appendChild(p); setTimeout(() => p.remove(), 4500);
  }
}
function reveal() {
  setView('gift'); studio.closeGift();
  setTimeout(() => { studio.openGift(); confetti(); toast(S.to.trim() ? `تخيّل وجّ ${S.to.trim()} هلّق` : 'هيك رح تكون اللحظة'); }, 1000);
}

// ---------- المقدّمة: الهدية بتنفتح والكوب بيطلع ----------
function start() {
  if (!introMode) return;
  studio.openGift(); confetti(60);
  setTimeout(() => {
    introMode = false; S.started = true;
    document.body.classList.remove('is-intro');
    sync3D(); updateOffset();
    go(S.step);
    setTimeout(() => studio.celebrate(), 500);
    setTimeout(() => $('#hint').classList.add('gone'), 7000);
  }, 1100);
}
$('#start').onclick = start;
if (S.started && S.step > 0) $('#startTxt').textContent = 'كمّل هديتك';
// عنوان بيطلع كلمة كلمة
$('#heroTitle').innerHTML = $('#heroTitle').textContent.trim().split(/\s+/).map((w, i) => `<span class="w" style="--i:${i}">${esc(w)}</span>`).join(' ');

function order() {
  if (!S.name.trim() || !S.phone.trim()) { toast('بس اسمك ورقمك لنقدر نتواصل معك'); $(!S.name.trim() ? '#f-name' : '#f-phone').focus(); return; }
  const cup = byId(cat.cups, S.cup), box = byId(cat.boxes, S.box);
  const msg = [
    `مرحبا ${cat.shop.name}، بدي اطلب هالهدية:`, '',
    `☕ ${cup.name} — ${colorName(cat.cupColors, S.cupColor) || S.cupColor}`,
    S.text && `✍️ الكتابة: ${S.text}${S.line2 ? ' / ' + S.line2 : ''} (خط ${byId(cat.fonts, S.font).name})`,
    `🎨 زخرفة: ${byId(cat.decorations, S.deco).name} · ملصق: ${byId(cat.stickers, S.sticker).name}`,
    box.w ? `🎁 بوكس ${box.name} — ${colorName(cat.boxColors, S.boxColor) || S.boxColor} · شريطة ${byId(cat.ribbons, S.ribbon).name}` : '📦 بدون بوكس',
    box.w && S.addons.length ? `✨ إضافات: ${S.addons.map((id) => (cat.addons.find((a) => a.id === id) || {}).name).filter(Boolean).join('، ')}` : '',
    S.message && `💌 الكرت: ${S.message}`,
    S.to && `👤 الهدية لـ: ${S.to}`, '',
    `💰 المجموع: ${money(total())}`, '',
    `الاسم: ${S.name}`, `الموبايل: ${S.phone}`, S.address && `العنوان: ${S.address}`, S.date && `تاريخ التوصيل: ${S.date}`,
  ].filter((x) => x !== false && x != null).join('\n');
  try {
    const orders = JSON.parse(localStorage.getItem(ORDERS_KEY) || '[]');
    orders.unshift({ at: new Date().toISOString(), total: total(), design: { ...S }, text: msg });
    localStorage.setItem(ORDERS_KEY, JSON.stringify(orders.slice(0, 200)));
  } catch (e) {}
  confetti();
  const url = `https://wa.me/${String(cat.shop.whatsapp).replace(/\D/g, '')}?text=${encodeURIComponent(msg)}`;
  let waBox = $('#waBox');
  if (!waBox) { waBox = document.createElement('div'); waBox.id = 'waBox'; waBox.className = 'group'; $('#stepBody').appendChild(waBox); }
  waBox.innerHTML = `<div class="tip"><i>✦</i><span>طلبك جاهز. إذا ما انفتح الواتساب لحالو، اكبس هون:</span></div><a class="btn wa" style="width:100%;text-decoration:none" href="${url}" target="_blank" rel="noopener">افتح واتساب وابعت الطلب</a>`;
  waBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  try { window.open(url, '_blank'); } catch (e) {}
}

// ---------- البداية ----------
render(); sync3D(); studio.setView('intro', true); updateOffset(); placeInk();
document.fonts?.ready.then(() => { sync3D(); placeInk(); });
cat.fonts.forEach((f) => document.fonts?.load(`700 80px ${f.css}`).then(sync3DSoon).catch(() => {}));
requestAnimationFrame(() => requestAnimationFrame(() => $('#loading').classList.add('gone')));   // أول ما ينرسم أول مشهد
