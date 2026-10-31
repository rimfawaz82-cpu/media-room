import { loadCatalog, saveCatalog, resetCatalog } from './catalog.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let cat = await loadCatalog();
let dirty = false;

const SHAPES = [['mug', 'ماغ'], ['latte', 'لاتيه'], ['travel', 'سفر'], ['glass', 'زجاج']];
const PATTERNS = [['none', 'بدون'], ['hearts', 'قلوب'], ['flowers', 'ورد'], ['stars', 'نجوم'], ['dots', 'نقط'], ['stripes', 'خطوط'], ['confetti', 'احتفال']];
const KINDS = [['chocolate', 'شوكولا'], ['rose', 'وردة'], ['card', 'كرت'], ['candle', 'شمعة'], ['teddy', 'دبدوب'], ['cookies', 'كوكيز'], ['other', 'علبة عامة']];

// كل قسم: الحقول يلي بتنعدّل
const SECTIONS = {
  shop: { title: 'إعدادات المتجر', form: [['name', 'اسم المتجر'], ['tagline', 'الشعار'], ['currency', 'العملة'], ['whatsapp', 'رقم واتساب (مع رمز البلد)'], ['delivery', 'سعر التوصيل', 'number']] },
  cups: { title: 'الأكواب', sub: 'أنواع الأكواب وأسعارها الأساسية. الشكل بيحدد كيف بيطلع بالـ3D.', cols: [['id', 'رمز'], ['name', 'الاسم'], ['desc', 'الوصف'], ['price', 'السعر', 'number'], ['shape', 'الشكل', SHAPES], ['badge', 'شارة']] },
  cupColors: { title: 'ألوان الأكواب', cols: [['name', 'الاسم'], ['hex', 'اللون', 'color']] },
  decorations: { title: 'الزخارف', sub: 'زخرفة جاهزة أو ارفع صورة نقشة (بتتكرر على الكوب).', cols: [['id', 'رمز'], ['name', 'الاسم'], ['price', 'السعر', 'number'], ['pattern', 'النقشة', PATTERNS], ['emoji', 'رمز صغير'], ['img', 'صورة نقشة', 'image']] },
  stickers: { title: 'الملصقات', sub: 'إيموجي أو صورة (PNG شفافة أحسن) بتنحط بنص الكوب فوق الكتابة.', cols: [['id', 'رمز'], ['name', 'الاسم'], ['price', 'السعر', 'number'], ['emoji', 'إيموجي'], ['img', 'صورة', 'image']] },
  fonts: { title: 'الخطوط', sub: 'اسم الخط لازم يكون محمّل بالصفحة (Google Fonts).', cols: [['id', 'رمز'], ['name', 'الاسم'], ['css', 'CSS font-family']] },
  textColors: { title: 'ألوان الكتابة', flat: true },
  boxes: { title: 'البوكسات', sub: 'القياسات بالسنتيمتر — البوكس بالـ3D بيطلع بنفس النسبة. خلّي w=0 لخيار "بدون بوكس".', cols: [['id', 'رمز'], ['name', 'الاسم'], ['desc', 'الوصف'], ['price', 'السعر', 'number'], ['w', 'عرض', 'number'], ['d', 'عمق', 'number'], ['h', 'ارتفاع', 'number'], ['badge', 'شارة']] },
  boxColors: { title: 'ألوان البوكس', cols: [['name', 'الاسم'], ['hex', 'اللون', 'color']] },
  ribbons: { title: 'الشرائط', cols: [['id', 'رمز'], ['name', 'الاسم'], ['price', 'السعر', 'number'], ['hex', 'اللون (فاضي = بدون)', 'color?']] },
  addons: { title: 'الإضافات', sub: 'النوع بيحدد شكلها جوّا البوكس.', cols: [['id', 'رمز'], ['name', 'الاسم'], ['price', 'السعر', 'number'], ['kind', 'النوع', KINDS], ['emoji', 'إيموجي'], ['img', 'صورة', 'image']] },
  occasions: { title: 'المناسبات', sub: 'كل مناسبة بتعبّي ألوان وتصميم مبدئي للزبون.', cols: [['id', 'رمز'], ['name', 'الاسم'], ['emoji', 'إيموجي'], ['text', 'جملة'], ['cup', 'لون الكوب', 'color'], ['box', 'لون البوكس', 'color'], ['ribbon', 'الشريطة', 'color'], ['pattern', 'زخرفة', PATTERNS], ['font', 'رمز الخط']] },
  orders: { title: 'الطلبات' },
};
let current = 'cups';

function mark() { dirty = true; $('#dirty').textContent = '● في تغييرات ما انحفظت'; }
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('on'), 2400); }

function cell(row, [key, label, type], ri) {
  const v = row[key] ?? '';
  const attrs = `data-r="${ri}" data-k="${key}"`;
  let html;
  if (Array.isArray(type)) html = `<select ${attrs}>${type.map(([val, n]) => `<option value="${val}" ${v === val ? 'selected' : ''}>${n}</option>`).join('')}</select>`;
  else if (type === 'color') html = `<input type="color" ${attrs} value="${esc(v || '#ffffff')}">`;
  else if (type === 'color?') html = `<span class="upl"><input type="color" ${attrs} value="${esc(v || '#ffffff')}"><button class="mini" data-clear="${ri}" data-k="${key}" title="بدون">${v ? '✕' : '∅'}</button></span>`;
  else if (type === 'image') html = `<span class="upl">${v ? `<img class="thumb" src="${esc(v)}" alt=""><button class="mini" data-clear="${ri}" data-k="${key}" title="شيل الصورة">✕</button>` : ''}<label>ارفع<input type="file" accept="image/*" hidden data-img="${ri}" data-k="${key}"></label></span>`;
  else html = `<input ${type === 'number' ? 'type="number" step="0.5" min="0"' : ''} ${attrs} value="${esc(v)}">`;
  return `<td data-l="${label}">${html}</td>`;
}

function render() {
  $('#side').innerHTML = Object.entries(SECTIONS).map(([k, s]) => `<button class="${k === current ? 'on' : ''}" data-sec="${k}">${s.title}</button>`).join('');
  const s = SECTIONS[current], c = $('#content');
  if (current === 'shop') {
    c.innerHTML = `<h2>${s.title}</h2><p class="sub">بتطلع بالهيدر وبرسالة الطلب.</p>
      <div class="note">⚠️ هالنسخة بتحفظ بمتصفّحك هون بس. لتطلع لكل الزباين: اضغط «تصدير JSON» وحط الملف باسم <b>catalog.json</b> جنب index.html (أو منربطها بقاعدة بيانات بالمرحلة الجاية).</div>
      <div class="form">${s.form.map(([k, l, t]) => `<label>${l}<input class="field" ${t === 'number' ? 'type="number" step="0.5"' : ''} data-shop="${k}" value="${esc(cat.shop[k])}"></label>`).join('')}</div>`;
  } else if (current === 'orders') {
    let orders = []; try { orders = JSON.parse(localStorage.getItem('cupstudio.orders.v1') || '[]'); } catch (e) {}
    c.innerHTML = `<h2>الطلبات</h2><p class="sub">الطلبات يلي انبعتت لواتساب من هالجهاز (${orders.length}).</p>
      ${orders.length ? orders.map((o) => `<div class="order"><b>${new Date(o.at).toLocaleString('ar')}</b>${esc(o.text)}</div>`).join('') : '<div class="note">لسّا ما في طلبات. الطلبات بتوصلك عالواتساب مباشرة.</div>'}`;
  } else if (s.flat) {
    c.innerHTML = `<h2>${s.title}</h2><p class="sub">الألوان يلي بيختار منها الزبون.</p>
      <div class="form" style="grid-template-columns:repeat(auto-fill,minmax(90px,1fr))">${cat[current].map((hex, i) => `<span class="upl"><input type="color" data-flat="${i}" value="${esc(hex)}"><button class="mini" data-del="${i}">✕</button></span>`).join('')}</div>
      <div class="actions"><button class="btn gold" data-add>+ زيد لون</button></div>`;
  } else {
    const rows = cat[current];
    c.innerHTML = `<h2>${s.title}</h2><p class="sub">${s.sub || ''}</p>
      <table><thead><tr>${s.cols.map(([, l]) => `<th>${l}</th>`).join('')}<th></th></tr></thead>
      <tbody>${rows.map((r, i) => `<tr>${s.cols.map((col) => cell(r, col, i)).join('')}<td data-l="ترتيب"><button class="mini" data-up="${i}" title="لفوق">↑</button><button class="mini" data-del="${i}" title="احذف">🗑</button></td></tr>`).join('')}</tbody></table>
      <div class="actions"><button class="btn gold" data-add>+ زيد عنصر</button></div>`;
  }
}

// تصغير الصور قبل الحفظ حتى ما يتعبّى التخزين
function shrink(file, max = 384) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => { const im = new Image(); im.onload = () => {
      const k = Math.min(1, max / Math.max(im.width, im.height)), c = document.createElement('canvas');
      c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
      c.getContext('2d').drawImage(im, 0, 0, c.width, c.height); res(c.toDataURL('image/png'));
    }; im.onerror = rej; im.src = fr.result; };
    fr.onerror = rej; fr.readAsDataURL(file);
  });
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('button'); if (!t) return;
  if (t.dataset.sec) { current = t.dataset.sec; render(); return; }
  const list = cat[current];
  if (t.hasAttribute('data-add')) {
    if (SECTIONS[current].flat) list.push('#c2405a');
    else { const row = {}; SECTIONS[current].cols.forEach(([k, , ty]) => (row[k] = ty === 'number' ? 0 : Array.isArray(ty) ? ty[0][0] : ty === 'color' ? '#e8b4c4' : '')); row.id = 'n' + Date.now().toString(36); row.name = 'جديد'; list.push(row); }
    mark(); render(); return;
  }
  if (t.dataset.del != null) { list.splice(+t.dataset.del, 1); mark(); render(); toast('انحذف — ما بيتثبّت لحتى تكبس حفظ'); return; }
  if (t.dataset.up != null) { const i = +t.dataset.up; if (i > 0) { [list[i - 1], list[i]] = [list[i], list[i - 1]]; mark(); render(); } return; }
  if (t.dataset.clear != null) { list[+t.dataset.clear][t.dataset.k] = ''; mark(); render(); }
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.dataset.shop) { cat.shop[t.dataset.shop] = t.type === 'number' ? +t.value : t.value; mark(); return; }
  if (t.dataset.flat != null) { cat[current][+t.dataset.flat] = t.value; mark(); return; }
  if (t.dataset.r != null) { const col = SECTIONS[current].cols.find(([k]) => k === t.dataset.k); cat[current][+t.dataset.r][t.dataset.k] = col[2] === 'number' ? +t.value : t.value; mark(); }
});
document.addEventListener('change', async (e) => {
  const t = e.target;
  if (t.dataset.img != null && t.files[0]) {
    try { cat[current][+t.dataset.img][t.dataset.k] = await shrink(t.files[0]); mark(); render(); } catch (err) { toast('ما قدرنا نقرا الصورة'); }
  }
});

$('#save').onclick = () => {
  try { saveCatalog(cat); dirty = false; $('#dirty').textContent = ''; toast('✓ انحفظ — فتّح الموقع لتشوف التغييرات'); }
  catch (e) { toast('التخزين امتلى — صغّر الصور أو قلّل عددها'); }
};
$('#reset').onclick = (e) => { const btn = e.currentTarget; if (!btn.dataset.sure) { btn.dataset.sure = 1; btn.textContent = 'أكيد؟ اكبس كمان مرة'; setTimeout(() => { delete btn.dataset.sure; btn.textContent = 'رجّع الافتراضي'; }, 3000); return; } { cat = resetCatalog(); dirty = false; $('#dirty').textContent = ''; render(); toast('رجعنا للافتراضي'); } };
$('#export').onclick = () => {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(cat, null, 2)], { type: 'application/json' }));
  a.download = 'catalog.json'; a.click();
};
$('#import').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try { cat = { ...cat, ...JSON.parse(await f.text()) }; mark(); render(); toast('انستورد — اضغط حفظ'); } catch (err) { toast('الملف مش JSON صالح'); }
};
window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
render();
