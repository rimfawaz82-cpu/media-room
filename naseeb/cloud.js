// =====================================================================
//  المزامنة الأونلاين للدفتر (Supabase)
//  الدفتر مكتوب لبيئة claude.ai ويطلب قاعدة بياناته عبر window.claude.use('db').
//  هالملف بيقدّم نفس الواجهة فوق Supabase، فكل التعديلات بتتشارك بين الشركاء
//  وبتوصل فوراً. كل سجل بالدفتر صف بجدول naseeb_kv (coll, id, data).
// =====================================================================
(function () {
  const CFG = window.NASEEB_CFG || {};
  window.NB_BLOB = '/_blob/';   // وين بتنقرا الصور (بيتغيّر لـ Supabase Storage تحت)
  if (!CFG.SUPABASE_URL || !CFG.SUPABASE_ANON_KEY || !window.supabase) return; // بيضل يحفظ على الجهاز

  const sb = window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, storageKey: 'naseeb-auth' }
  });
  const TABLE = 'naseeb_kv';
  // أنواع السجلات: الدفتر بيجمعها بـ"سلال" (cartons/b3 = {r: {id: rec}}) — هون كل سجل صف لحاله
  const RECS = new Set(['cartons', 'items', 'sales', 'orders', 'customers', 'dpay', 'moves', 'expenses']);
  const PAGE = 1000, CHUNK = 500;
  const BUCKET = 'naseeb';
  window.NB_BLOB = CFG.SUPABASE_URL + '/storage/v1/object/public/' + BUCKET + '/';

  const mkErr = (code, msg) => Object.assign(new Error(msg || code), { code });
  const wrap = e => mkErr('unavailable', (e && e.message) || String(e));
  const isObj = v => v && typeof v === 'object' && !Array.isArray(v);
  const split = path => { const i = path.indexOf('/'); return i < 0 ? [path, ''] : [path.slice(0, i), path.slice(i + 1)]; };

  // ---------- cache + listeners ----------
  const cache = {};        // coll -> Map(id -> data)
  const loaded = {};       // coll -> Promise
  const collSubs = {};     // coll -> Set({cb, err})
  const docSubs = {};      // path -> Set({cb, err})

  async function fetchColl(coll) {
    const m = new Map();
    for (let from = 0; ; from += PAGE) {
      const { data, error } = await sb.from(TABLE).select('id,data').eq('coll', coll).order('id').range(from, from + PAGE - 1);
      if (error) throw wrap(error);
      data.forEach(r => m.set(r.id, r.data));
      if (data.length < PAGE) break;
    }
    cache[coll] = m;
    return m;
  }
  function ensure(coll) { return loaded[coll] || (loaded[coll] = fetchColl(coll).catch(e => { delete loaded[coll]; throw e; })); }

  function collSnap(coll) {
    const m = cache[coll] || new Map();
    if (RECS.has(coll)) {
      const r = Object.fromEntries(m);
      return { docs: m.size ? [{ id: 'all', exists: true, data: () => ({ r }) }] : [], size: m.size ? 1 : 0, empty: !m.size };
    }
    const docs = [...m].map(([id, d]) => ({ id, exists: true, data: () => d }));
    return { docs, size: docs.length, empty: !docs.length };
  }
  function docSnap(path) {
    const [coll, id] = split(path);
    const d = cache[coll] && cache[coll].get(id);
    return { id, exists: d !== undefined, data: () => d };
  }
  function emit(coll, id) {
    (collSubs[coll] || []).forEach(s => { try { s.cb(collSnap(coll)); } catch (e) { console.error(e); } });
    const fire = p => (docSubs[p] || []).forEach(s => { try { s.cb(docSnap(p)); } catch (e) { console.error(e); } });
    if (id !== undefined) fire(coll + '/' + id);
    else Object.keys(docSubs).forEach(p => { if (split(p)[0] === coll) fire(p); });
  }
  async function reload(coll) {
    delete loaded[coll];
    try { await ensure(coll); emit(coll); }
    catch (e) { [...(collSubs[coll] || []), ...Object.keys(docSubs).filter(p => split(p)[0] === coll).flatMap(p => [...docSubs[p]])].forEach(s => s.err && s.err(e)); }
  }
  const watched = () => new Set([...Object.keys(collSubs), ...Object.keys(docSubs).map(p => split(p)[0])]);
  const reloadAll = () => watched().forEach(reload);

  function subscribe(table, key, cb, err) {
    const s = { cb, err }; (table[key] ||= new Set()).add(s);
    return () => table[key].delete(s);
  }

  // ---------- realtime ----------
  let live = false;
  function startRealtime() {
    if (live) return; live = true;
    let wasUp = false;
    sb.channel('naseeb-kv')
      .on('postgres_changes', { event: '*', schema: 'public', table: TABLE }, p => {
        const row = p.eventType === 'DELETE' ? p.old : p.new;
        if (!row || !row.coll || !cache[row.coll]) return;
        if (p.eventType === 'DELETE') cache[row.coll].delete(row.id);
        else cache[row.coll].set(row.id, row.data);
        emit(row.coll, row.id);
      })
      .subscribe(status => {
        if (status === 'SUBSCRIBED') { if (wasUp) reloadAll(); wasUp = true; } // رجع الاتصال: جيب يلي فاتنا
      });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') reloadAll(); });
    window.addEventListener('online', reloadAll);
  }

  // ---------- writes ----------
  async function upsertRows(rows) {
    for (let i = 0; i < rows.length; i += CHUNK) {
      const { error } = await sb.from(TABLE).upsert(rows.slice(i, i + CHUNK), { onConflict: 'coll,id' });
      if (error) throw wrap(error);
    }
    rows.forEach(r => (cache[r.coll] ||= new Map()).set(r.id, r.data));
  }
  async function getRow(coll, id) {
    const { data, error } = await sb.from(TABLE).select('data').eq('coll', coll).eq('id', id).maybeSingle();
    if (error) throw wrap(error);
    return data ? data.data : undefined;
  }

  function doc(path) {
    const [coll, id] = split(path);
    const rec = RECS.has(coll);
    const recRows = obj => Object.entries((obj && obj.r) || {}).map(([rid, data]) => ({ coll, id: rid, data }));
    return {
      id,
      async get() {
        if (rec) return { id, exists: false, data: () => undefined };   // السلال ما إلها وجود هون
        const d = await getRow(coll, id);
        return { id, exists: d !== undefined, data: () => d };
      },
      async set(obj) { return upsertRows(rec ? recRows(obj) : [{ coll, id, data: obj || {} }]); },
      async update(obj) {
        if (rec) return upsertRows(recRows(obj));
        const cur = await getRow(coll, id);
        if (cur === undefined) throw mkErr('invalid_argument', 'no document');
        const next = { ...cur };
        for (const k in obj) next[k] = isObj(cur[k]) && isObj(obj[k]) ? { ...cur[k], ...obj[k] } : obj[k];
        return upsertRows([{ coll, id, data: next }]);
      },
      async delete() {
        let q = sb.from(TABLE).delete().eq('coll', coll);
        if (!(rec && id === 'all')) q = q.eq('id', id);
        const { error } = await q;
        if (error) throw wrap(error);
        if (rec && id === 'all') cache[coll] = new Map(); else if (cache[coll]) cache[coll].delete(id);
      },
      onSnapshot(cb, err) {
        const un = subscribe(docSubs, path, cb, err);
        ensure(coll).then(() => cb(docSnap(path)), e => err && err(e));
        return un;
      }
    };
  }
  function collection(coll) {
    return {
      async get() { await ensure(coll); return collSnap(coll); },
      onSnapshot(cb, err) {
        const un = subscribe(collSubs, coll, cb, err);
        ensure(coll).then(() => cb(collSnap(coll)), e => err && err(e));
        return un;
      }
    };
  }
  const db = { doc, collection };

  // ---------- login ----------
  const css = `
#nb-auth{position:fixed;inset:0;z-index:100;background:var(--bg,#F3F5F9);display:grid;place-items:center;padding:24px 16px;font-family:var(--f,system-ui);direction:rtl}
#nb-auth form{width:min(360px,100%);background:var(--surface,#fff);border:1px solid var(--line,#E1E5EE);border-radius:14px;padding:26px 22px;display:flex;flex-direction:column;gap:12px;box-shadow:var(--shadow,0 10px 30px -8px rgba(15,29,58,.16))}
#nb-auth h1{margin:0;font-family:var(--fh,inherit);font-size:20px;color:var(--ink,#0F1D3A)}
#nb-auth p{margin:0 0 4px;color:var(--muted,#687390);font-size:13px}
#nb-auth label{display:flex;flex-direction:column;gap:5px;font-size:12.5px;color:var(--ink2,#3A4660);font-weight:500}
#nb-auth input{border:1px solid var(--line2,#CBD2DF);background:var(--surface,#fff);color:var(--ink,#0F1D3A);border-radius:8px;padding:10px 12px;font:inherit;font-size:15px;direction:ltr;text-align:left}
#nb-auth button{border:0;background:var(--acc,#FF6A1A);color:#0F1D3A;font:inherit;font-weight:700;font-size:15px;border-radius:9px;padding:11px;margin-top:6px;cursor:pointer}
#nb-auth button[disabled]{opacity:.6}
#nb-auth .nb-err{color:var(--bad,#B0372A);font-size:13px;min-height:18px}
#nb-auth img{height:44px;width:auto;align-self:flex-start}
.nb-out{margin-inline-start:auto;border:0;background:none;color:inherit;font:inherit;font-size:12px;text-decoration:underline;cursor:pointer;padding:0}`;

  async function isMember(email) {
    const { data, error } = await sb.from('naseeb_members').select('email').eq('email', String(email || '').toLowerCase()).maybeSingle();
    if (error) throw error;
    return !!data;
  }

  function showLogin(msg) {
    return new Promise(resolve => {
      const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
      const w = document.createElement('div'); w.id = 'nb-auth';
      const logo = document.querySelector('.brand-mark');
      w.innerHTML = `<form autocomplete="on">
        ${logo ? `<img src="${logo.src}" alt="">` : ''}
        <h1>دفتر مزاد نصيب</h1>
        <p>فوت بإيميلك وكلمة السر حتى تشوف الدفتر المشترك.</p>
        <label>الإيميل<input name="email" type="email" autocomplete="username" required></label>
        <label>كلمة السر<input name="password" type="password" autocomplete="current-password" required></label>
        <div class="nb-err"></div>
        <button type="submit">دخول</button>
      </form>`;
      document.body.appendChild(w);
      const f = w.querySelector('form'), errEl = w.querySelector('.nb-err'), btn = w.querySelector('button');
      errEl.textContent = msg || '';
      f.addEventListener('submit', async e => {
        e.preventDefault();
        btn.disabled = true; errEl.textContent = '';
        try {
          const { data, error } = await sb.auth.signInWithPassword({ email: f.email.value.trim(), password: f.password.value });
          if (error) { errEl.textContent = /invalid/i.test(error.message) ? 'الإيميل أو كلمة السر غلط' : 'ما زبط الدخول — تأكد من الإنترنت'; return; }
          if (!(await isMember(data.user.email))) { await sb.auth.signOut(); errEl.textContent = 'هالحساب مش مسموحله يفوت عالدفتر'; return; }
          w.remove(); resolve();
        } catch (e2) { errEl.textContent = 'ما زبط الدخول — تأكد من الإنترنت'; }
        finally { btn.disabled = false; }
      });
    });
  }

  async function signedIn() {
    const { data } = await sb.auth.getSession();
    const s = data && data.session;
    if (s) {
      try { if (await isMember(s.user.email)) return; await sb.auth.signOut(); return showLogin('هالحساب مش مسموحله يفوت عالدفتر'); }
      catch (e) { return; }   // بلا إنترنت: منكمّل بالجلسة المحفوظة
    }
    return showLogin();
  }

  // زر خروج تحت القائمة الجانبية
  function addSignOut() {
    const foot = document.getElementById('sidefoot');
    if (!foot) return;
    const put = () => {
      if (foot.querySelector('.nb-out')) return;
      const b = document.createElement('button'); b.className = 'nb-out'; b.type = 'button'; b.textContent = 'خروج';
      b.addEventListener('click', async () => { await sb.auth.signOut(); location.reload(); });
      foot.appendChild(b);
    };
    put(); new MutationObserver(put).observe(foot, { childList: true });
  }

  // ---------- photos (Supabase Storage) ----------
  // بيقدّم نفس واجهة assets تبع claude.ai: كل صورة ملف بإسم عشوائي (32 حرف) بالـ bucket
  const assets = {
    async upload(blob) {
      const id = [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
      const { error } = await sb.storage.from(BUCKET).upload(id, blob, { contentType: blob.type || 'image/jpeg', cacheControl: '31536000' });
      if (error) throw mkErr(/quota|size|exceed/i.test(error.message || '') ? 'quota_or_state' : 'unavailable', error.message);
      return { id, url: window.NB_BLOB + id };
    },
    async delete(id) {
      const { error } = await sb.storage.from(BUCKET).remove([id]);
      if (error) throw wrap(error);
    },
    async list() { return { usage: null, assets: [] }; }
  };

  // ---------- one-time move of photos and descriptions from claude.ai ----------
  // migration/data.json + migration/img/<id>.jpg (exported from the claude.ai ledger).
  // Shown as a bar until meta/migration is marked done; safe to re-run (finished photos are skipped).
  const MIG_DONE_KEY = 'naseeb-mig-done';
  async function offerMigration() {
    let info;
    try { const r = await fetch('migration/data.json', { cache: 'no-store' }); if (!r.ok) return; info = await r.json(); } catch (e) { return; }
    const mark = await getRow('meta', 'migration').catch(() => undefined);
    if (mark && mark.done) return;
    const bar = document.createElement('div');
    bar.style.cssText = 'position:fixed;inset-inline:12px;bottom:calc(84px + env(safe-area-inset-bottom,0px));z-index:40;background:#0F1D3A;color:#fff;border-radius:12px;padding:12px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;font:14px var(--f,system-ui);box-shadow:0 10px 30px -8px rgba(0,0,0,.4);direction:rtl';
    const txt = document.createElement('span'); txt.style.flex = '1';
    txt.textContent = `في ${info.images.length} صورة و${Object.keys(info.itemx).length} وصف قطعة من دفتر claude.ai لسّا ما انتقلوا.`;
    const btn = document.createElement('button');
    btn.style.cssText = 'border:0;background:#FF6A1A;color:#0F1D3A;font:inherit;font-weight:700;border-radius:8px;padding:8px 14px;cursor:pointer';
    btn.textContent = 'انقل هلّق';
    bar.append(txt, btn); document.body.appendChild(bar);
    btn.addEventListener('click', async () => {
      btn.disabled = true; btn.style.opacity = '.6';
      try { await runMigration(info, msg => { txt.textContent = msg; }); txt.textContent = 'خلص النقل ✓ — عم يحمّل من جديد…'; setTimeout(() => location.reload(), 1200); }
      catch (e) { txt.textContent = 'وقف النقل: ' + (e && e.message || e) + ' — كبّس كمان مرة بيكمّل من وين وقف.'; btn.disabled = false; btn.style.opacity = ''; btn.textContent = 'كمّل'; }
    });
  }
  async function runMigration(info, say) {
    say('عم ينقل الأوصاف…');
    const rows = [];
    for (const coll of ['itemx', 'intake']) for (const [id, data] of Object.entries(info[coll] || {})) rows.push({ coll, id, data });
    await upsertRows(rows);
    let done = new Set();
    try { done = new Set(JSON.parse(localStorage.getItem(MIG_DONE_KEY) || '[]')); } catch (e) {}
    const todo = info.images.filter(id => !done.has(id));
    let n = info.images.length - todo.length, failed = 0;
    const save = () => { try { localStorage.setItem(MIG_DONE_KEY, JSON.stringify([...done])); } catch (e) {} };
    async function one(id) {
      for (let t = 0; t < 3; t++) {
        try {
          const r = await fetch('migration/img/' + id + '.jpg', { cache: 'no-store' });
          if (!r.ok) throw new Error('ما لقى الصورة ' + id);
          const { error } = await sb.storage.from(BUCKET).upload(id, await r.blob(), { contentType: 'image/jpeg', cacheControl: '31536000' });
          if (error && !/exist|duplicate/i.test(error.message || '')) throw new Error(error.message);
          done.add(id); n++; if (n % 10 === 0) save();
          say(`عم ينقل الصور: ${n} من ${info.images.length}`);
          return;
        } catch (e) { if (t === 2) { failed++; console.warn(e); } else await new Promise(r => setTimeout(r, 1500 * (t + 1))); }
      }
    }
    const queue = todo.slice();
    await Promise.all(Array.from({ length: 4 }, async () => { while (queue.length) await one(queue.shift()); }));
    save();
    if (failed) throw new Error(failed + ' صورة ما انتقلت');
    await upsertRows([{ coll: 'meta', id: 'migration', data: { done: true, at: new Date().toISOString(), images: info.images.length } }]);
  }

  // ---------- one-time price update prepared in Claude (migration/prices-*.json) ----------
  // Writes only the price fields (and name) into items that already exist here; marks itself done.
  async function applyPrices() {
    let info;
    try { const r = await fetch('migration/prices-20261013.json', { cache: 'no-store' }); if (!r.ok) return; info = await r.json(); } catch (e) { return; }
    const tag = info.tag || 'prices';
    const mark = await getRow('meta', tag).catch(() => undefined);
    if (mark && mark.done) return;
    await ensure('items');
    const have = cache.items || new Map(); const rows = [];
    for (const [id, f] of Object.entries(info.items || {})) {
      const cur = have.get(id); if (!cur) continue;
      const next = { ...cur }; let ch = false;
      for (const k of ['marketPrice', 'priceSrc', 'priceUrl', 'priceAt', 'name']) if (f[k] !== undefined && f[k] !== '' && String(cur[k] ?? '') !== String(f[k])) { next[k] = f[k]; ch = true; }
      if (k_empty(f.priceUrl) && cur.priceUrl && f.priceSrc === 'تقدير Claude') { next.priceUrl = ''; ch = true; }
      if (ch) rows.push({ coll: 'items', id, data: next });
    }
    function k_empty(v) { return v === '' || v == null; }
    if (rows.length) await upsertRows(rows);
    await upsertRows([{ coll: 'meta', id: tag, data: { done: true, at: new Date().toISOString(), n: rows.length } }]);
    if (rows.length) {
      const bar = document.createElement('div');
      bar.style.cssText = 'position:fixed;inset-inline:12px;bottom:calc(84px + env(safe-area-inset-bottom,0px));z-index:40;background:#0F1D3A;color:#fff;border-radius:12px;padding:12px 14px;font:14px var(--f,system-ui);direction:rtl;box-shadow:0 10px 30px -8px rgba(0,0,0,.4)';
      bar.textContent = 'تحدّثت أسعار ' + rows.length + ' قطعة ✓ — عم يحمّل من جديد…';
      document.body.appendChild(bar); setTimeout(() => location.reload(), 1500);
    }
  }

  let ready = null;
  const getDb = () => ready || (ready = signedIn().then(() => { startRealtime(); addSignOut(); offerMigration(); applyPrices().catch(e => console.warn('prices', e)); return db; }));

  window.claude = {
    async use(name) {
      if (name === 'db') return getDb();
      if (name === 'assets') return getDb().then(() => assets);
      return null;
    }
  };
})();
