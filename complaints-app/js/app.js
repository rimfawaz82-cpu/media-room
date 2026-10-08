/* =====================================================================
   نظام إدارة شكاوى المواطنين - بلدية حارة حريك
   التطبيق الكامل (واجهة المستخدم). لا يحتاج إلى أي تعديل للتشغيل.
   ===================================================================== */
(function () {
  'use strict';

  const CFG = window.APP_CONFIG || {};
  const $app = document.getElementById('app');
  const $dlg = document.getElementById('dlg');

  if (!CFG.SUPABASE_URL || CFG.SUPABASE_URL.includes('XXXX') || !window.supabase) {
    $app.innerHTML = `<div class="login-wrap"><div class="login-card">
      <h1>التطبيق غير مربوط بقاعدة البيانات بعد</h1>
      <p>افتح الملف <b>js/config.js</b> وضع فيه رابط Supabase والمفتاح (anon public) كما في دليل التشغيل.</p>
    </div></div>`;
    return;
  }

  const sb = window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY, {
    auth: { persistSession: true, autoRefreshToken: true }
  });

  // ------------------------------------------------------------------
  // الثوابت والنصوص
  // ------------------------------------------------------------------
  const ST = {
    pending:     'بانتظار التحويل',
    new:         'جديدة - لم تُشاهد',
    seen:        'تمت المشاهدة',
    in_progress: 'قيد المتابعة',
    resolved:    'تمت المعالجة',
    failed:      'تعذّرت المعالجة',
    returned:    'أُعيدت للمسؤول'
  };
  const ST_ORDER = ['pending', 'new', 'seen', 'in_progress', 'resolved', 'failed', 'returned'];
  const PR = { normal: 'عادية', urgent: 'مستعجلة', emergency: 'طارئة' };
  const ROLE = { admin: 'مسؤول الشكاوى', department: 'قسم', deputy: 'نائب الرئيس' };
  const OPEN = ['new', 'seen', 'in_progress'];
  const APPROVAL = { none: '', pending: 'بانتظار الموافقة', approved: 'موافَق عليها', rejected: 'مرفوضة' };

  // ------------------------------------------------------------------
  // الحالة العامة
  // ------------------------------------------------------------------
  const S = {
    session: null,
    me: null,             // ملف المستخدم الحالي
    settings: { unseen_hours: 24, unresolved_days: 7, municipality_name: 'بلدية حارة حريك' },
    departments: [],
    deptMap: {},
    areas: [],
    profiles: {},
    complaints: [],
    loadedAt: 0,
    unread: 0,
    filters: {},
    dirty: false,         // يوجد نص مكتوب لم يُحفظ
    channel: null,
    currentId: null
  };

  // ------------------------------------------------------------------
  // أدوات مساعدة
  // ------------------------------------------------------------------
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const dtFmt = new Intl.DateTimeFormat('ar-LB-u-nu-latn', {
    timeZone: 'Asia/Beirut', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  });
  const dFmt = new Intl.DateTimeFormat('ar-LB-u-nu-latn', {
    timeZone: 'Asia/Beirut', year: 'numeric', month: '2-digit', day: '2-digit'
  });
  const fmtDT = (d) => (d ? dtFmt.format(new Date(d)) : '');
  const fmtD = (d) => (d ? dFmt.format(new Date(d)) : '');

  function fmtDuration(ms) {
    if (ms == null || isNaN(ms)) return '—';
    const h = Math.round(ms / 3600000);
    if (h < 1) return 'أقل من ساعة';
    if (h < 24) return h + ' ساعة';
    const d = Math.floor(h / 24), r = h % 24;
    return d + ' يوم' + (r ? ' و' + r + ' ساعة' : '');
  }

  function toast(msg, type) {
    const el = document.createElement('div');
    el.className = 'toast ' + (type || '');
    el.textContent = msg;
    el.onclick = () => el.remove();
    document.getElementById('toasts').appendChild(el);
    setTimeout(() => el.remove(), type === 'err' ? 7000 : 4000);
  }

  function errMsg(e) {
    if (!e) return 'حدث خطأ';
    const m = e.message || String(e);
    if (/Invalid login credentials/i.test(m)) return 'اسم الدخول أو كلمة السر غير صحيحة';
    if (/banned/i.test(m)) return 'هذا الحساب معطّل. راجع مسؤول الشكاوى';
    if (/Failed to fetch|NetworkError/i.test(m)) return 'لا يوجد اتصال بالإنترنت';
    return m;
  }

  async function rpc(name, args) {
    const { data, error } = await sb.rpc(name, args || {});
    if (error) throw error;
    return data;
  }

  // جلب كل الصفوف (Supabase يعطي 1000 صف كحد أقصى في الطلب الواحد)
  async function fetchAll(build) {
    const out = [];
    const size = 1000;
    for (let from = 0; ; from += size) {
      const { data, error } = await build().range(from, from + size - 1);
      if (error) throw error;
      out.push(...data);
      if (data.length < size) break;
    }
    return out;
  }

  const isAdmin = () => S.me && S.me.role === 'admin';
  const isDeputy = () => S.me && S.me.role === 'deputy';
  const isDept = () => S.me && S.me.role === 'department';
  const deptName = (id) => (S.deptMap[id] ? S.deptMap[id].name : id || '');
  const userName = (id) => (S.profiles[id] ? S.profiles[id].full_name : '');

  function appLink(id) {
    return location.origin + location.pathname + '#/c/' + id;
  }

  // تحويل رقم لبناني إلى صيغة واتساب الدولية (961...)
  function waPhone(p) {
    let d = String(p || '').replace(/\D/g, '');
    if (!d) return '';
    if (d.startsWith('00')) d = d.slice(2);
    if (d.startsWith('961')) return d;
    if (d.startsWith('0')) d = d.slice(1);
    return '961' + d;
  }
  function waUrl(phone, text) {
    const p = waPhone(phone);
    return 'https://wa.me/' + p + '?text=' + encodeURIComponent(text);
  }

  // ------------------------------------------------------------------
  // حساب الحالة والتأخير
  // ------------------------------------------------------------------
  function lateInfo(a) {
    const now = Date.now();
    const since = now - new Date(a.assigned_at).getTime();
    const unseen = a.status === 'new' && since > S.settings.unseen_hours * 3600000;
    const unresolved = OPEN.includes(a.status) && since > S.settings.unresolved_days * 86400000;
    return { unseen, unresolved, any: unseen || unresolved };
  }

  function complaintStatus(c) {
    const as = c.assignments || [];
    if (isDept()) return as[0] ? as[0].status : 'new';
    if (!as.length) return 'pending';
    if (c.closed_at) return as.some((a) => a.status === 'resolved') ? 'resolved' : 'failed';
    if (as.some((a) => a.status === 'returned')) return 'returned';
    if (as.some((a) => a.status === 'new')) return 'new';
    if (as.some((a) => a.status === 'seen')) return 'seen';
    return 'in_progress';
  }

  function isLate(c) {
    return (c.assignments || []).some((a) => lateInfo(a).any);
  }

  function lateReasons(c) {
    const r = [];
    (c.assignments || []).forEach((a) => {
      const l = lateInfo(a);
      if (l.unseen) r.push(deptName(a.department_id) + ': لم تُشاهد خلال ' + S.settings.unseen_hours + ' ساعة');
      else if (l.unresolved) r.push(deptName(a.department_id) + ': لم تُعالج خلال ' + S.settings.unresolved_days + ' أيام');
    });
    return r;
  }

  const pendingApproval = (c) => (c.assignments || []).some((a) => a.approval_status === 'pending');
  const SOURCE_BADGE = { whatsapp: '<span class="badge">واتساب</span>', citizen: '<span class="badge src-citizen">👤 من المواطن</span>' };

  const stBadge = (st) => `<span class="badge st-${st}">${esc(ST[st] || st)}</span>`;
  const prBadge = (p) => `<span class="badge pr-${p}">${p === 'emergency' ? '🚨 ' : ''}${esc(PR[p] || p)}</span>`;

  function seenLine(a) {
    if (a.seen_at) return `👁️ شوهدت: ${esc(userName(a.seen_by) || '')} — ${esc(fmtDT(a.seen_at))}`;
    return '⭕ لم تُشاهد بعد';
  }

  // ------------------------------------------------------------------
  // تحميل البيانات
  // ------------------------------------------------------------------
  async function loadRefData() {
    const [st, deps, ars, profs] = await Promise.all([
      sb.from('app_settings').select('*').eq('id', 1).maybeSingle(),
      sb.from('departments').select('*').order('sort'),
      sb.from('areas').select('*').order('sort').order('name'),
      sb.from('profiles').select('id, username, full_name, role, department_id, phone, active, created_at').order('created_at')
    ]);
    for (const r of [st, deps, ars, profs]) if (r.error) throw r.error;
    if (st.data) S.settings = st.data;
    S.departments = deps.data;
    S.deptMap = Object.fromEntries(deps.data.map((d) => [d.id, d]));
    S.areas = ars.data;
    S.profiles = Object.fromEntries(profs.data.map((p) => [p.id, p]));
  }

  async function loadComplaints() {
    S.complaints = await fetchAll(() =>
      sb.from('complaints').select('*, assignments(*)').order('created_at', { ascending: false }).order('id', { ascending: false })
    );
    S.loadedAt = Date.now();
  }

  async function loadUnread() {
    const { count } = await sb.from('notifications').select('id', { count: 'exact', head: true })
      .eq('user_id', S.me.id).is('read_at', null);
    S.unread = count || 0;
    const b = document.getElementById('bell-count');
    if (b) {
      b.textContent = S.unread > 99 ? '99+' : S.unread;
      b.classList.toggle('hidden', !S.unread);
    }
    if (navigator.setAppBadge) {
      try { S.unread ? navigator.setAppBadge(S.unread) : navigator.clearAppBadge(); } catch (e) { /* غير مدعوم */ }
    }
  }

  // ------------------------------------------------------------------
  // التحديث المباشر (Realtime)
  // ------------------------------------------------------------------
  let refreshTimer = null;
  function scheduleRefresh(complaintId) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(async () => {
      try {
        await loadComplaints();
        const r = parseRoute();
        if (S.dirty) {
          showUpdateBanner();
        } else if (r.name !== 'new' && r.name !== 'settings') {
          if (r.name !== 'detail' || !complaintId || String(complaintId) === String(r.id)) render(true);
        }
      } catch (e) { console.warn(e); }
    }, 700);
  }

  function showUpdateBanner() {
    if (document.getElementById('upd-banner')) return;
    const b = document.createElement('div');
    b.className = 'banner no-print';
    b.id = 'upd-banner';
    b.innerHTML = '<span>🔄 وصلت تحديثات جديدة.</span><button class="btn sm">عرض التحديثات</button>';
    b.querySelector('button').onclick = () => { S.dirty = false; render(true); };
    const main = document.querySelector('main');
    if (main) main.prepend(b);
  }

  function subscribeRealtime() {
    if (S.channel) sb.removeChannel(S.channel);
    const onChange = (payload) => {
      const row = payload.new && Object.keys(payload.new).length ? payload.new : payload.old || {};
      scheduleRefresh(row.complaint_id || row.id);
    };
    S.channel = sb.channel('live-' + S.me.id)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'complaints' }, onChange)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'assignments' }, onChange)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'notes' }, onChange)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'events' }, onChange)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'notifications', filter: 'user_id=eq.' + S.me.id },
        (p) => onNotification(p.new))
      .subscribe();
  }

  async function onNotification(n) {
    loadUnread();
    toast('🔔 ' + n.title);
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        const reg = await navigator.serviceWorker.getRegistration();
        const opts = {
          body: n.body || '',
          icon: 'icons/icon-192.png',
          badge: 'icons/icon-192.png',
          tag: 'n' + n.id,
          data: { url: n.complaint_id ? appLink(n.complaint_id) : location.href }
        };
        if (reg) reg.showNotification(n.title, opts);
        else new Notification(n.title, opts);
      } catch (e) { /* تجاهل */ }
    }
  }

  // ------------------------------------------------------------------
  // التنقّل بين الشاشات
  // ------------------------------------------------------------------
  function parseRoute() {
    const h = (location.hash || '#/').slice(1);
    const [path, qs] = h.split('?');
    const parts = path.split('/').filter(Boolean);
    const q = Object.fromEntries(new URLSearchParams(qs || ''));
    if (!parts.length) return { name: 'dashboard', q };
    if (parts[0] === 'c' && parts[1]) return { name: 'detail', id: Number(parts[1]), q };
    if (parts[0] === 'edit' && parts[1]) return { name: 'edit', id: Number(parts[1]), q };
    return { name: parts[0], q };
  }

  function go(hash) {
    if (location.hash === hash) render();
    else location.hash = hash;
  }

  window.addEventListener('hashchange', () => {
    if (S.dirty && !confirm('لديك نص لم يُحفظ. هل تريد المغادرة؟')) {
      return;
    }
    S.dirty = false;
    render();
  });

  function navItems() {
    const items = [{ h: '#/', ico: '📊', t: isDept() ? 'لوحة القسم' : 'لوحة التحكم', r: 'dashboard' },
      { h: '#/list', ico: '📋', t: 'الشكاوى', r: 'list' }];
    if (isAdmin()) items.push({ h: '#/new', ico: '➕', t: 'شكوى جديدة', r: 'new' });
    items.push({ h: '#/notifications', ico: '🔔', t: 'الإشعارات', r: 'notifications' });
    if (!isDept()) items.push({ h: '#/report', ico: '🖨️', t: 'التقرير الشهري', r: 'report', cls: 'desktop-only' });
    items.push({ h: '#/settings', ico: '⚙️', t: isAdmin() ? 'الإعدادات' : 'حسابي', r: 'settings' });
    return items;
  }

  function shell() {
    const sub = isDept() ? deptName(S.me.department_id) : ROLE[S.me.role];
    $app.innerHTML = `
      <header class="topbar">
        <a class="brand" href="#/" style="color:#fff;text-decoration:none">
          <img src="icons/logo.png" alt="">
          <span>${esc(S.settings.municipality_name)} — الشكاوى</span>
        </a>
        <span class="user">${esc(S.me.full_name)} · ${esc(sub)}</span>
        <a class="icon-btn" href="#/notifications" title="الإشعارات">🔔<span id="bell-count" class="badge-count hidden">0</span></a>
        <button class="icon-btn" id="btn-logout" title="خروج">🚪</button>
      </header>
      <nav class="nav" id="nav"></nav>
      <main id="main"></main>`;
    document.getElementById('btn-logout').onclick = logout;
    loadUnread();
  }

  function renderNav(active) {
    const nav = document.getElementById('nav');
    if (!nav) return;
    nav.innerHTML = navItems().map((i) =>
      `<a href="${i.h}" class="${i.r === active ? 'active' : ''} ${i.cls || ''}"><span class="ico">${i.ico}</span><span>${esc(i.t)}</span></a>`
    ).join('');
  }

  let renderSeq = 0;
  async function render(silent) {
    if (!S.me) return;
    if (!document.getElementById('main')) shell();
    const r = parseRoute();
    renderNav(r.name === 'detail' || r.name === 'edit' ? 'list' : r.name);
    const main = document.getElementById('main');
    const seq = ++renderSeq;
    const keepScroll = silent ? window.scrollY : 0;
    if (!silent) main.innerHTML = '<div class="spinner">جارٍ التحميل…</div>';
    try {
      if (!S.loadedAt || Date.now() - S.loadedAt > 60000) await loadComplaints();
      if (seq !== renderSeq) return;
      const views = {
        dashboard: viewDashboard, list: viewList, new: viewNew, edit: viewNew, detail: viewDetail,
        notifications: viewNotifications, settings: viewSettings, report: viewReport
      };
      const fn = views[r.name] || viewDashboard;
      await fn(main, r, seq);
      if (silent) window.scrollTo(0, keepScroll);
      else window.scrollTo(0, 0);
    } catch (e) {
      console.error(e);
      if (seq === renderSeq) main.innerHTML = `<div class="card"><div class="err-box">${esc(errMsg(e))}</div>
        <button class="btn mt" onclick="location.reload()">إعادة المحاولة</button></div>`;
    }
  }

  // ------------------------------------------------------------------
  // تسجيل الدخول والخروج
  // ------------------------------------------------------------------
  function viewLogin(msg) {
    $app.innerHTML = `
      <div class="login-wrap">
        <form class="login-card" id="login-form" autocomplete="on">
          <img class="logo" src="icons/logo.png" alt="شعار بلدية حارة حريك">
          <h1>${esc(S.settings.municipality_name || 'بلدية حارة حريك')}</h1>
          <p class="sub">نظام إدارة شكاوى المواطنين</p>
          <label class="f" for="lg-user">اسم الدخول</label>
          <input type="text" id="lg-user" autocomplete="username" autocapitalize="none" spellcheck="false" dir="ltr" required>
          <label class="f" for="lg-pass">كلمة السر</label>
          <input type="password" id="lg-pass" autocomplete="current-password" dir="ltr" required>
          <button class="btn big block mt" type="submit" id="lg-btn">دخول</button>
          <div id="lg-err" class="err-box ${msg ? '' : 'hidden'}">${esc(msg || '')}</div>
          <p class="sub mt"><a href="shakwa.html">هل أنت مواطن؟ قدّم شكوى أو تابع شكواك من هنا</a></p>
        </form>
      </div>`;
    document.getElementById('login-form').onsubmit = async (ev) => {
      ev.preventDefault();
      const btn = document.getElementById('lg-btn');
      const errBox = document.getElementById('lg-err');
      btn.disabled = true; btn.textContent = 'جارٍ الدخول…';
      errBox.classList.add('hidden');
      const user = document.getElementById('lg-user').value.trim().toLowerCase();
      const pass = document.getElementById('lg-pass').value;
      const { error } = await sb.auth.signInWithPassword({ email: user + '@' + CFG.LOGIN_DOMAIN, password: pass });
      if (error) {
        errBox.textContent = errMsg(error);
        errBox.classList.remove('hidden');
        btn.disabled = false; btn.textContent = 'دخول';
        return;
      }
      await start();
    };
  }

  async function logout() {
    if (!confirm('هل تريد تسجيل الخروج؟')) return;
    if (S.channel) sb.removeChannel(S.channel);
    await sb.auth.signOut();
    S.me = null; S.complaints = []; S.loadedAt = 0;
    viewLogin();
  }

  async function start() {
    const { data } = await sb.auth.getSession();
    S.session = data.session;
    if (!S.session) return viewLogin();
    const { data: me, error } = await sb.from('profiles').select('*').eq('id', S.session.user.id).maybeSingle();
    if (error || !me || !me.active) {
      await sb.auth.signOut();
      return viewLogin(error ? errMsg(error) : 'هذا الحساب غير مفعّل');
    }
    S.me = me;
    $app.innerHTML = '<div class="spinner">جارٍ التحميل…</div>';
    try {
      await loadRefData();
      if (isAdmin()) rpc('check_overdue').catch(() => {});
      await loadComplaints();
    } catch (e) {
      $app.innerHTML = `<div class="login-wrap"><div class="login-card"><div class="err-box">${esc(errMsg(e))}</div>
        <button class="btn block mt" onclick="location.reload()">إعادة المحاولة</button></div></div>`;
      return;
    }
    shell();
    subscribeRealtime();
    render();
  }

  // ------------------------------------------------------------------
  // لوحة التحكم
  // ------------------------------------------------------------------
  function deptStats(deptId) {
    const as = [];
    S.complaints.forEach((c) => (c.assignments || []).forEach((a) => { if (a.department_id === deptId) as.push(a); }));
    const count = (st) => as.filter((a) => a.status === st).length;
    const closed = as.filter((a) => a.closed_at && (a.status === 'resolved' || a.status === 'failed'));
    const seen = as.filter((a) => a.seen_at);
    const avg = (arr, f) => (arr.length ? arr.reduce((s, a) => s + f(a), 0) / arr.length : null);
    return {
      total: as.length,
      new: count('new'), seen: count('seen'), in_progress: count('in_progress'),
      resolved: count('resolved'), failed: count('failed'), returned: count('returned'),
      late: as.filter((a) => lateInfo(a).any).length,
      avgClose: avg(closed, (a) => new Date(a.closed_at) - new Date(a.assigned_at)),
      avgSeen: avg(seen, (a) => new Date(a.seen_at) - new Date(a.assigned_at))
    };
  }

  function complaintCard(c) {
    const st = complaintStatus(c);
    const late = isLate(c);
    const chips = (c.assignments || []).map((a) => {
      const l = lateInfo(a);
      return `<span class="dept-chip" style="${l.any ? 'border-color:var(--danger)' : ''}">
        <b>${esc(deptName(a.department_id))}</b>: ${esc(ST[a.status])}
        ${a.seen_at ? `<span class="muted">· 👁️ ${esc(userName(a.seen_by))} ${esc(fmtDT(a.seen_at))}</span>`
          : '<span style="color:var(--danger)">· ⭕ لم تُشاهد</span>'}
      </span>`;
    }).join('');
    return `
      <a class="card c-item ${late ? 'late' : ''}" href="#/c/${c.id}">
        <div class="c-head">
          <span class="c-serial">${esc(c.serial)}</span>
          ${prBadge(c.priority)} ${stBadge(st)}
          ${late ? '<span class="badge late">⏰ متأخرة</span>' : ''}
          ${!isDept() && c.deputy_seen_at ? '<span class="badge deputy">👁️ نائب الرئيس</span>' : ''}
          ${pendingApproval(c) ? '<span class="badge approval">⏳ بانتظار موافقة نائب الرئيس</span>' : ''}
          ${SOURCE_BADGE[c.source] || ''}
          <span class="c-date">${esc(fmtDT(c.created_at))}</span>
        </div>
        <div class="c-body">${esc(c.body)}</div>
        ${c.area || c.address ? `<div class="small muted">📍 ${esc([c.area, c.address].filter(Boolean).join(' — '))}</div>` : ''}
        ${chips ? `<div class="c-depts">${chips}</div>` : ''}
      </a>`;
  }

  async function viewDashboard(main) {
    const cs = S.complaints;
    const counts = Object.fromEntries(ST_ORDER.map((s) => [s, 0]));
    cs.forEach((c) => { counts[complaintStatus(c)]++; });
    const lateList = cs.filter(isLate);
    const todayStr = fmtD(new Date());
    const today = cs.filter((c) => fmtD(c.created_at) === todayStr).length;

    const shown = isDept() ? ['new', 'seen', 'in_progress', 'resolved', 'failed', 'returned']
      : ['pending', 'new', 'seen', 'in_progress', 'returned', 'resolved', 'failed'];
    const cards = shown.filter((s) => s !== 'pending' || counts.pending)
      .map((s) => `<a class="stat st-${s}" href="#/list?status=${s}"><div class="num">${counts[s]}</div><div class="lbl">${esc(ST[s])}</div></a>`)
      .join('');

    let deptTable = '';
    if (!isDept()) {
      const rows = S.departments.map((d) => {
        const s = deptStats(d.id);
        return `<tr>
          <td><a href="#/list?dept=${esc(d.id)}"><b>${esc(d.name)}</b></a></td>
          <td class="num">${s.total}</td>
          <td class="num">${s.new}</td><td class="num">${s.seen}</td><td class="num">${s.in_progress}</td>
          <td class="num">${s.resolved}</td><td class="num">${s.failed}</td><td class="num">${s.returned}</td>
          <td class="num" style="${s.late ? 'color:var(--danger)' : ''}">${s.late}</td>
          <td class="num">${esc(fmtDuration(s.avgSeen))}</td>
          <td class="num">${esc(fmtDuration(s.avgClose))}</td>
        </tr>`;
      }).join('');
      deptTable = `
        <div class="card">
          <h2>حسب الأقسام</h2>
          <div class="table-wrap"><table class="t">
            <thead><tr><th>القسم</th><th class="num">المجموع</th><th class="num">لم تُشاهد</th><th class="num">شوهدت</th>
              <th class="num">قيد المتابعة</th><th class="num">عولجت</th><th class="num">تعذّرت</th><th class="num">أُعيدت</th>
              <th class="num">متأخرة</th><th class="num">متوسط وقت المشاهدة</th><th class="num">متوسط وقت المعالجة</th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>
        </div>`;
    } else {
      const s = deptStats(S.me.department_id);
      deptTable = `<div class="card"><h2>أداء القسم</h2>
        <dl class="kv"><dt>متوسط وقت المشاهدة</dt><dd>${esc(fmtDuration(s.avgSeen))}</dd>
        <dt>متوسط وقت المعالجة</dt><dd>${esc(fmtDuration(s.avgClose))}</dd></dl></div>`;
    }

    const attention = isAdmin() ? cs.filter((c) => ['pending', 'returned'].includes(complaintStatus(c))) : [];
    const awaiting = cs.filter(pendingApproval);
    const newOnes = isDept() ? cs.filter((c) => complaintStatus(c) === 'new') : [];

    main.innerHTML = `
      <div class="row between mb">
        <h1>${isDept() ? esc(deptName(S.me.department_id)) : 'لوحة التحكم'}</h1>
        ${isAdmin() ? '<a class="btn big" href="#/new">➕ شكوى جديدة</a>' : ''}
      </div>
      <div class="grid stats mb">
        <a class="stat" href="#/list"><div class="num">${cs.length}</div><div class="lbl">كل الشكاوى</div></a>
        <a class="stat" href="#/list?today=1"><div class="num">${today}</div><div class="lbl">وردت اليوم</div></a>
        ${!isDept() || awaiting.length ? `<a class="stat st-approval" href="#/list?approval=1"><div class="num">${awaiting.length}</div><div class="lbl">⏳ بانتظار موافقة نائب الرئيس</div></a>` : ''}
        <a class="stat late" href="#/list?late=1"><div class="num">${lateList.length}</div><div class="lbl">⏰ متأخرة</div></a>
        ${cards}
      </div>
      ${isDeputy() && awaiting.length ? `<h2>⏳ بانتظار موافقتك (${awaiting.length})</h2>${awaiting.map(complaintCard).join('')}` : ''}
      ${newOnes.length ? `<h2>🆕 شكاوى جديدة لم تفتحها بعد (${newOnes.length})</h2>${newOnes.slice(0, 20).map(complaintCard).join('')}` : ''}
      ${attention.length ? `<h2>⚠️ تحتاج انتباهك (${attention.length})</h2>${attention.slice(0, 20).map(complaintCard).join('')}` : ''}
      ${deptTable}
      <h2>⏰ الشكاوى المتأخرة (${lateList.length})</h2>
      <p class="muted small">متأخرة = لم تُشاهد خلال ${S.settings.unseen_hours} ساعة، أو لم تُعالج خلال ${S.settings.unresolved_days} أيام.</p>
      ${lateList.length ? lateList.slice(0, 30).map(complaintCard).join('') : '<div class="card empty">لا توجد شكاوى متأخرة 👍</div>'}
      ${lateList.length > 30 ? '<a class="btn light block" href="#/list?late=1">عرض كل المتأخرة</a>' : ''}
    `;
  }

  // ------------------------------------------------------------------
  // قائمة الشكاوى مع البحث والفلترة
  // ------------------------------------------------------------------
  function applyFilters(list, f) {
    const q = (f.q || '').trim().toLowerCase();
    const from = f.from ? new Date(f.from + 'T00:00:00').getTime() : null;
    const to = f.to ? new Date(f.to + 'T23:59:59').getTime() : null;
    const todayStr = fmtD(new Date());
    return list.filter((c) => {
      const t = new Date(c.created_at).getTime();
      if (from && t < from) return false;
      if (to && t > to) return false;
      if (f.today && fmtD(c.created_at) !== todayStr) return false;
      if (f.area && c.area !== f.area) return false;
      if (f.priority && c.priority !== f.priority) return false;
      if (f.late && !isLate(c)) return false;
      if (f.approval && !pendingApproval(c)) return false;
      if (f.source && c.source !== f.source) return false;
      if (f.dept) {
        const a = (c.assignments || []).find((x) => x.department_id === f.dept);
        if (!a) return false;
        if (f.status && a.status !== f.status) return false;
      } else if (f.status && complaintStatus(c) !== f.status) return false;
      if (q) {
        const hay = [c.serial, c.body, c.citizen_name, c.citizen_phone, c.area, c.address].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  async function viewList(main, r) {
    const f = Object.assign({}, r.q);
    const opts = (arr, sel) => arr.map(([v, t]) => `<option value="${esc(v)}" ${String(sel || '') === String(v) ? 'selected' : ''}>${esc(t)}</option>`).join('');
    const statuses = (isDept() ? ST_ORDER.filter((s) => s !== 'pending') : ST_ORDER).map((s) => [s, ST[s]]);

    main.innerHTML = `
      <div class="row between mb">
        <h1>الشكاوى</h1>
        <div class="row no-print">
          <button class="btn light sm" id="x-excel">📊 Excel</button>
          <button class="btn light sm" id="x-pdf">📄 PDF / طباعة</button>
        </div>
      </div>
      <div class="card no-print">
        <input type="search" id="f-q" placeholder="🔍 بحث: رقم الشكوى، نص، اسم، هاتف، شارع…" value="${esc(f.q || '')}">
        <div class="filters mt">
          ${isDept() ? '' : `<div><label>القسم</label><select id="f-dept"><option value="">الكل</option>${opts(S.departments.map((d) => [d.id, d.name]), f.dept)}</select></div>`}
          <div><label>الحالة</label><select id="f-status"><option value="">الكل</option>${opts(statuses, f.status)}</select></div>
          <div><label>المنطقة</label><select id="f-area"><option value="">الكل</option>${opts(S.areas.map((a) => [a.name, a.name]), f.area)}</select></div>
          <div><label>الأولوية</label><select id="f-priority"><option value="">الكل</option>${opts(Object.entries(PR), f.priority)}</select></div>
          <div><label>من تاريخ</label><input type="date" id="f-from" value="${esc(f.from || '')}"></div>
          <div><label>إلى تاريخ</label><input type="date" id="f-to" value="${esc(f.to || '')}"></div>
          <div><label>&nbsp;</label><label class="check-row"><input type="checkbox" id="f-late" ${f.late ? 'checked' : ''}> المتأخرة فقط</label></div>
          <div><label>&nbsp;</label><label class="check-row"><input type="checkbox" id="f-approval" ${f.approval ? 'checked' : ''}> بانتظار الموافقة</label></div>
          ${isDept() ? '' : `<div><label>المصدر</label><select id="f-source"><option value="">الكل</option>${opts([['manual', 'إدخال يدوي'], ['citizen', 'من المواطن'], ['whatsapp', 'واتساب']], f.source)}</select></div>`}
          <div><label>&nbsp;</label><button class="btn gray sm block" id="f-clear">مسح الفلاتر</button></div>
        </div>
      </div>
      <div id="list-count" class="muted mb"></div>
      <div id="list-items"></div>
      <div id="list-more"></div>`;

    let limit = 50;
    let filtered = [];
    const draw = () => {
      filtered = applyFilters(S.complaints, f);
      document.getElementById('list-count').textContent = 'عدد النتائج: ' + filtered.length;
      document.getElementById('list-items').innerHTML = filtered.length
        ? filtered.slice(0, limit).map(complaintCard).join('')
        : '<div class="card empty">لا توجد شكاوى مطابقة</div>';
      document.getElementById('list-more').innerHTML = filtered.length > limit
        ? '<button class="btn light block" id="more-btn">عرض المزيد</button>' : '';
      const mb = document.getElementById('more-btn');
      if (mb) mb.onclick = () => { limit += 50; draw(); };
    };
    const sync = () => {
      const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
      history.replaceState(null, '', '#/list' + (qs ? '?' + qs : ''));
    };
    const bind = (id, key, ev) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener(ev || 'change', () => {
        f[key] = el.type === 'checkbox' ? (el.checked ? '1' : '') : el.value;
        delete f.today;
        limit = 50; sync(); draw();
      });
    };
    bind('f-q', 'q', 'input'); bind('f-dept', 'dept'); bind('f-status', 'status'); bind('f-area', 'area');
    bind('f-priority', 'priority'); bind('f-from', 'from'); bind('f-to', 'to'); bind('f-late', 'late'); bind('f-approval', 'approval'); bind('f-source', 'source');
    document.getElementById('f-clear').onclick = () => go('#/list');
    document.getElementById('x-excel').onclick = () => exportExcel(filtered, 'الشكاوى');
    document.getElementById('x-pdf').onclick = () => printList(filtered, f);
    draw();
  }

  // ------------------------------------------------------------------
  // التصدير: Excel و PDF
  // ------------------------------------------------------------------
  function exportRows(list) {
    return list.map((c) => {
      const as = c.assignments || [];
      return {
        'رقم الشكوى': c.serial,
        'التاريخ': fmtDT(c.created_at),
        'الأولوية': PR[c.priority],
        'الحالة': ST[complaintStatus(c)],
        'متأخرة': isLate(c) ? 'نعم' : '',
        'المنطقة': c.area,
        'العنوان': c.address,
        'اسم المواطن': c.citizen_name,
        'هاتف المواطن': c.citizen_phone,
        'نص الشكوى': c.body,
        'الأقسام': as.map((a) => deptName(a.department_id)).join('، '),
        'حالة كل قسم': as.map((a) => deptName(a.department_id) + ': ' + ST[a.status]).join(' | '),
        'المشاهدة': as.map((a) => deptName(a.department_id) + ': ' + (a.seen_at ? userName(a.seen_by) + ' ' + fmtDT(a.seen_at) : 'لم تُشاهد')).join(' | '),
        'النتيجة': as.filter((a) => a.result).map((a) => deptName(a.department_id) + ': ' + a.result).join(' | '),
        'تاريخ الإقفال': fmtDT(c.closed_at),
        'مدة المعالجة': c.closed_at ? fmtDuration(new Date(c.closed_at) - new Date(c.created_at)) : '',
        'المصدر': c.source === 'citizen' ? 'من المواطن' : c.source === 'whatsapp' ? 'واتساب' : 'إدخال يدوي',
        'موافقة نائب الرئيس': as.filter((a) => a.approval_status !== 'none').map((a) => deptName(a.department_id) + ': ' + APPROVAL[a.approval_status]).join(' | '),
        'اطّلاع نائب الرئيس': isDept() ? '' : (c.deputy_seen_at ? fmtDT(c.deputy_seen_at) : 'لا')
      };
    });
  }

  function exportExcel(list, name) {
    if (!window.XLSX) { toast('مكتبة Excel لم تُحمَّل بعد، حاول بعد لحظات', 'err'); return; }
    const rows = exportRows(list);
    const ws = XLSX.utils.json_to_sheet(rows);
    ws['!cols'] = Object.keys(rows[0] || { a: 1 }).map((k) => ({ wch: k === 'نص الشكوى' ? 60 : k === 'النتيجة' ? 45 : 18 }));
    const wb = XLSX.utils.book_new();
    wb.Workbook = { Views: [{ RTL: true }] };
    XLSX.utils.book_append_sheet(wb, ws, 'الشكاوى');
    XLSX.writeFile(wb, name + ' ' + new Date().toISOString().slice(0, 10) + '.xlsx');
  }

  function printList(list, f) {
    const desc = [];
    if (f.dept) desc.push('القسم: ' + deptName(f.dept));
    if (f.status) desc.push('الحالة: ' + ST[f.status]);
    if (f.area) desc.push('المنطقة: ' + f.area);
    if (f.priority) desc.push('الأولوية: ' + PR[f.priority]);
    if (f.from || f.to) desc.push('الفترة: ' + (f.from || '…') + ' إلى ' + (f.to || '…'));
    if (f.late) desc.push('المتأخرة فقط');
    if (f.approval) desc.push('بانتظار موافقة نائب الرئيس');
    const area = document.getElementById('print-area');
    area.innerHTML = `<div class="report">
      <h1>${esc(S.settings.municipality_name)} — قائمة الشكاوى</h1>
      <div class="sub">${esc(desc.join(' · ') || 'كل الشكاوى')} · العدد: ${list.length} · تاريخ الطباعة: ${esc(fmtDT(new Date()))}</div>
      <table class="t"><thead><tr><th>الرقم</th><th>التاريخ</th><th>الأولوية</th><th>المنطقة</th><th>الشكوى</th><th>الأقسام والحالة</th><th>النتيجة</th></tr></thead>
      <tbody>${list.map((c) => `<tr>
        <td>${esc(c.serial)}${isLate(c) ? '<br><b style="color:#dc2626">متأخرة</b>' : ''}</td>
        <td>${esc(fmtDT(c.created_at))}</td><td>${esc(PR[c.priority])}</td>
        <td>${esc([c.area, c.address].filter(Boolean).join(' - '))}</td>
        <td>${esc(c.body.length > 220 ? c.body.slice(0, 220) + '…' : c.body)}</td>
        <td>${(c.assignments || []).map((a) => esc(deptName(a.department_id) + ': ' + ST[a.status])).join('<br>')}</td>
        <td>${(c.assignments || []).filter((a) => a.result).map((a) => esc(a.result)).join('<br>')}</td>
      </tr>`).join('')}</tbody></table></div>`;
    document.body.classList.add('printing-list');
    const done = () => { document.body.classList.remove('printing-list'); window.removeEventListener('afterprint', done); };
    window.addEventListener('afterprint', done);
    setTimeout(() => { window.print(); setTimeout(done, 1000); }, 100);
  }

  // ------------------------------------------------------------------
  // إدخال / تعديل شكوى
  // ------------------------------------------------------------------
  async function viewNew(main, r) {
    if (!isAdmin()) { main.innerHTML = '<div class="card">غير مسموح</div>'; return; }
    const editing = r.name === 'edit';
    let c = { body: '', citizen_name: '', citizen_phone: '', area: '', address: '', priority: 'normal', assignments: [] };
    if (editing) {
      const { data, error } = await sb.from('complaints').select('*, assignments(*)').eq('id', r.id).maybeSingle();
      if (error) throw error;
      if (!data) { main.innerHTML = '<div class="card">الشكوى غير موجودة</div>'; return; }
      c = data;
    }
    const areaOpts = S.areas.map((a) => `<option ${a.name === c.area ? 'selected' : ''}>${esc(a.name)}</option>`).join('');
    const extraArea = c.area && !S.areas.some((a) => a.name === c.area) ? `<option selected>${esc(c.area)}</option>` : '';

    main.innerHTML = `
      <h1>${editing ? 'تعديل الشكوى ' + esc(c.serial) : '➕ شكوى جديدة'}</h1>
      <form class="card" id="cf">
        <label class="f" for="cf-body">نص الشكوى * <span class="muted small">(انسخه من واتساب والصقه هنا)</span></label>
        <textarea id="cf-body" class="big" required placeholder="الصق نص الشكوى هنا…">${esc(c.body)}</textarea>
        <div class="row mt"><button type="button" class="btn gray sm" id="cf-paste">📋 لصق من الحافظة</button></div>

        <div class="grid two">
          <div><label class="f" for="cf-name">اسم المواطن (اختياري)</label>
            <input type="text" id="cf-name" value="${esc(c.citizen_name)}"></div>
          <div><label class="f" for="cf-phone">رقم هاتف المواطن (اختياري)</label>
            <input type="tel" id="cf-phone" dir="ltr" placeholder="03 123 456" value="${esc(c.citizen_phone)}"></div>
          <div><label class="f" for="cf-area">المنطقة</label>
            <select id="cf-area"><option value="">— اختر المنطقة —</option>${areaOpts}${extraArea}</select></div>
          <div><label class="f" for="cf-addr">الشارع / العنوان التفصيلي</label>
            <input type="text" id="cf-addr" value="${esc(c.address)}" placeholder="مثال: الشارع العام، قرب الفرن"></div>
        </div>

        <label class="f">درجة الأولوية</label>
        <div class="choices">
          ${Object.entries(PR).map(([k, v]) => `<label class="choice pr-${k}"><input type="radio" name="cf-pr" value="${k}" ${c.priority === k ? 'checked' : ''}><span>${esc(v)}</span></label>`).join('')}
        </div>

        ${editing ? '' : `
        <label class="f">تحويل إلى القسم المختص * <span class="muted small">(يمكن اختيار أكثر من قسم)</span></label>
        <div class="choices">
          ${S.departments.filter((d) => d.active).map((d) => `<label class="choice"><input type="checkbox" name="cf-dept" value="${esc(d.id)}"><span>${esc(d.name)}</span></label>`).join('')}
        </div>

        <label class="f">صور ومرفقات</label>
        <input type="file" id="cf-files" multiple accept="image/*,application/pdf,audio/*,video/*">
        <div class="muted small">تُضغط الصور تلقائياً لتوفير المساحة. الحد الأقصى 10 ميغابايت للملف.</div>`}

        <div class="row mt">
          <button class="btn big grow" type="submit" id="cf-save">${editing ? '💾 حفظ التعديلات' : '💾 حفظ وتحويل'}</button>
          <a class="btn gray big" href="${editing ? '#/c/' + c.id : '#/'}">إلغاء</a>
        </div>
      </form>`;

    const form = document.getElementById('cf');
    form.addEventListener('input', () => { S.dirty = true; });
    document.getElementById('cf-paste').onclick = async () => {
      try {
        const t = await navigator.clipboard.readText();
        const ta = document.getElementById('cf-body');
        ta.value = ta.value ? ta.value + '\n' + t : t;
        S.dirty = true;
      } catch (e) { toast('اضغط مطوّلاً داخل المربع واختر "لصق"', 'err'); }
    };
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      const btn = document.getElementById('cf-save');
      const body = document.getElementById('cf-body').value.trim();
      const pr = (form.querySelector('input[name=cf-pr]:checked') || {}).value || 'normal';
      const args = {
        p_body: body,
        p_citizen_name: document.getElementById('cf-name').value,
        p_citizen_phone: document.getElementById('cf-phone').value,
        p_area: document.getElementById('cf-area').value,
        p_address: document.getElementById('cf-addr').value,
        p_priority: pr
      };
      if (!body) { toast('نص الشكوى مطلوب', 'err'); return; }
      btn.disabled = true; btn.textContent = 'جارٍ الحفظ…';
      try {
        if (editing) {
          await rpc('update_complaint', Object.assign({ p_id: c.id }, args));
          S.dirty = false;
          toast('تم حفظ التعديلات', 'ok');
          await loadComplaints();
          go('#/c/' + c.id);
          return;
        }
        const depts = [...form.querySelectorAll('input[name=cf-dept]:checked')].map((i) => i.value);
        if (!depts.length) { toast('اختر قسماً واحداً على الأقل', 'err'); btn.disabled = false; btn.textContent = '💾 حفظ وتحويل'; return; }
        const created = await rpc('create_complaint', Object.assign(args, { p_departments: depts }));
        const files = document.getElementById('cf-files').files;
        if (files.length) {
          btn.textContent = 'جارٍ رفع المرفقات…';
          await uploadFiles(created.id, files, 'complaint');
        }
        S.dirty = false;
        await loadComplaints();
        toast('تم حفظ الشكوى رقم ' + created.serial + ' وتحويلها', 'ok');
        go('#/c/' + created.id + '?sent=1');
      } catch (e) {
        toast(errMsg(e), 'err');
        btn.disabled = false; btn.textContent = editing ? '💾 حفظ التعديلات' : '💾 حفظ وتحويل';
      }
    };
  }

  // ضغط الصور قبل الرفع
  function compressImage(file) {
    return new Promise((resolve) => {
      if (!/^image\/(jpeg|png|webp|heic|heif)/i.test(file.type)) return resolve(file);
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const max = 1600;
        let { width: w, height: h } = img;
        if (w > max || h > max) { const k = max / Math.max(w, h); w = Math.round(w * k); h = Math.round(h * k); }
        const cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        cv.getContext('2d').drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        cv.toBlob((b) => resolve(b && b.size < file.size ? new File([b], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' }) : file),
          'image/jpeg', 0.8);
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }

  async function uploadFiles(cid, files, kind) {
    let failed = 0;
    for (const original of files) {
      try {
        const f = await compressImage(original);
        if (f.size > 10 * 1024 * 1024) { toast('الملف ' + original.name + ' أكبر من 10 ميغابايت', 'err'); failed++; continue; }
        const ext = (f.name.split('.').pop() || 'bin').toLowerCase().replace(/[^a-z0-9]/g, '') || 'bin';
        const path = cid + '/' + Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '.' + ext;
        const up = await sb.storage.from('attachments').upload(path, f, { contentType: f.type || 'application/octet-stream' });
        if (up.error) throw up.error;
        await rpc('add_attachment', { p_id: cid, p_path: path, p_name: original.name, p_mime: f.type, p_size: f.size, p_kind: kind });
      } catch (e) {
        failed++;
        toast('تعذّر رفع ' + original.name + ': ' + errMsg(e), 'err');
      }
    }
    return failed;
  }

  // ------------------------------------------------------------------
  // تفاصيل الشكوى
  // ------------------------------------------------------------------
  function waDeptText(c) {
    return `*${S.settings.municipality_name} — شكوى رقم ${c.serial}*\n` +
      `الأولوية: ${PR[c.priority]}\n` +
      (c.area || c.address ? `المكان: ${[c.area, c.address].filter(Boolean).join(' — ')}\n` : '') +
      `\n${c.body.length > 600 ? c.body.slice(0, 600) + '…' : c.body}\n\n` +
      `الرجاء فتح الشكوى ومتابعتها من الرابط:\n${appLink(c.id)}`;
  }

  function waCitizenText(c) {
    const as = c.assignments || [];
    const closed = !!c.closed_at;
    const results = as.filter((a) => a.result && a.status !== 'returned')
      .map((a) => (as.length > 1 ? `• ${deptName(a.department_id)}: ` : '') + a.result).join('\n');
    return `مرحباً${c.citizen_name ? ' ' + c.citizen_name : ''}،\n` +
      `بخصوص شكواكم رقم ${c.serial} لدى ${S.settings.municipality_name}:\n\n` +
      (closed ? `النتيجة:\n${results || ST[complaintStatus(c)]}\n` : `شكواكم قيد المتابعة لدى القسم المختص، وسنعلمكم بالنتيجة.\n`) +
      `\nشكراً لتواصلكم معنا.`;
  }

  async function viewDetail(main, r, seq) {
    const id = r.id;
    S.currentId = id;
    // تسجيل المشاهدة تلقائياً (للقسم ونائب الرئيس)
    if (!isAdmin()) {
      try { await rpc('mark_viewed', { p_id: id }); } catch (e) { /* يُعالج أدناه إن لم تكن مرئية */ }
    } else {
      rpc('mark_viewed', { p_id: id }).catch(() => {});
    }
    const [cR, nR, eR, attR, vR] = await Promise.all([
      sb.from('complaints').select('*, assignments(*)').eq('id', id).maybeSingle(),
      sb.from('notes').select('*').eq('complaint_id', id).order('created_at'),
      sb.from('events').select('*').eq('complaint_id', id).order('created_at').order('id'),
      sb.from('attachments').select('*').eq('complaint_id', id).order('created_at'),
      isDept() ? Promise.resolve({ data: [] }) : sb.from('complaint_views').select('*').eq('complaint_id', id).order('first_viewed_at')
    ]);
    for (const x of [cR, nR, eR, attR, vR]) if (x.error) throw x.error;
    if (seq !== renderSeq) return;
    const c = cR.data;
    if (!c) { main.innerHTML = '<div class="card empty">الشكوى غير موجودة أو ليست من صلاحياتك</div>'; return; }
    // تحديث النسخة المحلية
    const idx = S.complaints.findIndex((x) => x.id === c.id);
    if (idx >= 0) S.complaints[idx] = c;

    const notes = nR.data, events = eR.data, atts = attR.data, views = vR.data || [];
    const st = complaintStatus(c);
    const late = isLate(c);
    const reasons = lateReasons(c);

    // روابط مؤقتة للمرفقات
    const signed = {};
    if (atts.length) {
      const { data } = await sb.storage.from('attachments').createSignedUrls(atts.map((a) => a.path), 3600);
      (data || []).forEach((d) => { if (d.signedUrl) signed[d.path] = d.signedUrl; });
    }
    const thumb = (a) => {
      const u = signed[a.path] || '#';
      return /^image\//.test(a.mime)
        ? `<a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="${esc(a.file_name)}" loading="lazy"></a>`
        : `<a href="${esc(u)}" target="_blank" rel="noopener"><span class="file">📎 ${esc(a.file_name || 'ملف')}</span></a>`;
    };
    const mainAtts = atts.filter((a) => a.kind === 'complaint');

    const deptCards = (c.assignments || []).sort((a, b) => a.id - b.id).map((a) => {
      const l = lateInfo(a);
      const canAct = isAdmin() || (isDept() && S.me.department_id === a.department_id);
      const open = OPEN.includes(a.status);
      const afterAtts = atts.filter((x) => x.kind === 'after' && x.department_id === a.department_id);
      const dep = S.deptMap[a.department_id] || {};
      let actions = '';
      const pend = a.approval_status === 'pending';
      if (canAct && open) {
        if (a.status !== 'in_progress') actions += `<button class="btn warn" data-act="in_progress" data-a="${a.id}">▶️ بدء المتابعة</button>`;
        if (!pend) {
          actions += `<button class="btn ok" data-act="resolved" data-a="${a.id}">✅ تمت المعالجة</button>`;
          actions += `<button class="btn danger" data-act="failed" data-a="${a.id}">⛔ تعذّرت المعالجة</button>`;
          actions += `<button class="btn purple" data-act="req_approval" data-a="${a.id}">🖊️ طلب موافقة نائب الرئيس</button>`;
        }
        if (isDept()) actions += `<button class="btn gray" data-act="returned" data-a="${a.id}">↩️ ليست من اختصاصنا</button>`;
      }
      if (isDeputy() && pend) {
        actions += `<button class="btn ok" data-act="approve" data-a="${a.id}">✅ موافقة</button>`;
        actions += `<button class="btn danger" data-act="reject" data-a="${a.id}">❌ رفض</button>`;
      }
      if (isAdmin()) {
        if (!open) actions += `<button class="btn light" data-act="reopen" data-a="${a.id}">🔄 إعادة فتح</button>`;
        actions += `<a class="btn wa" target="_blank" rel="noopener" href="${esc(waUrl(dep.whatsapp, waDeptText(c)))}">💬 إرسال للقسم عبر واتساب</a>`;
        actions += `<button class="btn gray sm" data-act="remove" data-a="${a.id}">✖ إلغاء التحويل</button>`;
      }
      if (isDept() && S.me.department_id === a.department_id) {
        actions += `<button class="btn light" data-act="after" data-a="${a.id}">📷 إرفاق صورة بعد المعالجة</button>`;
      }
      return `
        <div class="dept-card ${l.any ? 'late' : ''}">
          <div class="row between">
            <h3 style="margin:0">${esc(deptName(a.department_id))}</h3>
            <div class="row">${stBadge(a.status)}${l.any ? '<span class="badge late">⏰ متأخرة</span>' : ''}</div>
          </div>
          <div class="mt small">
            <div>📨 حُوِّلت: ${esc(fmtDT(a.assigned_at))}</div>
            <div>${a.seen_at ? `<span class="badge seen-ok">${seenLine(a)}</span>` : `<span class="badge unseen">${seenLine(a)}</span>`}</div>
            ${a.started_at ? `<div>▶️ بدء المتابعة: ${esc(fmtDT(a.started_at))}</div>` : ''}
            ${a.closed_at ? `<div>🏁 الإقفال: ${esc(fmtDT(a.closed_at))} — ${esc(userName(a.closed_by))} (المدة: ${esc(fmtDuration(new Date(a.closed_at) - new Date(a.assigned_at)))})</div>` : ''}
          </div>
          ${a.result ? `<div class="result-box ${a.status}"><b>${a.status === 'resolved' ? 'النتيجة' : a.status === 'failed' ? 'سبب التعذّر' : 'سبب الإعادة'}:</b>
            <div class="pre">${esc(a.result)}</div></div>` : ''}
          ${a.approval_status !== 'none' ? `<div class="approval-box ${a.approval_status}">
            <b>${a.approval_status === 'pending' ? '⏳ بانتظار موافقة نائب الرئيس' : a.approval_status === 'approved' ? '✅ وافق نائب الرئيس' : '❌ رفض نائب الرئيس'}</b>
            <div class="small">طلبها: ${esc(userName(a.approval_requested_by))} — ${esc(fmtDT(a.approval_requested_at))}</div>
            <div class="pre"><b>السبب:</b> ${esc(a.approval_reason || '')}</div>
            ${a.approval_decided_at ? `<div class="small mt">القرار: ${esc(fmtDT(a.approval_decided_at))}</div>` : ''}
            ${a.approval_note ? `<div class="pre"><b>ملاحظة نائب الرئيس:</b> ${esc(a.approval_note)}</div>` : ''}
            ${pend && canAct ? '<div class="small mt">لا يمكن إقفال الشكوى قبل قرار نائب الرئيس.</div>' : ''}
          </div>` : ''}
          ${afterAtts.length ? `<div class="mt"><b>صور بعد المعالجة:</b><div class="thumbs mt">${afterAtts.map(thumb).join('')}</div></div>` : ''}
          ${actions ? `<div class="actions no-print">${actions}</div>` : ''}
        </div>`;
    }).join('');

    const notesHtml = notes.map((n) => {
      const who = userName(n.author_id) || '';
      const label = n.kind === 'directive' ? '📌 توجيه من نائب الرئيس' + (n.department_id ? ' إلى ' + deptName(n.department_id) : '')
        : n.kind === 'admin' ? (n.department_id ? '✉️ من مسؤول الشكاوى إلى ' + deptName(n.department_id) : '🔒 ملاحظة داخلية')
          : '📝 ' + deptName(n.department_id);
      return `<div class="note ${n.kind}"><div class="meta">${esc(label)} · ${esc(who)} · ${esc(fmtDT(n.created_at))}</div><div class="pre">${esc(n.body)}</div></div>`;
    }).join('');

    const noteTargets = (isAdmin() || isDeputy()) && (c.assignments || []).length
      ? `<select id="nt-target" class="mt">
          <option value="">${isAdmin() ? '🔒 ملاحظة داخلية (لا تراها الأقسام)' : 'لكل الأقسام المعنية'}</option>
          ${(c.assignments || []).map((a) => `<option value="${esc(a.department_id)}">إلى: ${esc(deptName(a.department_id))}</option>`).join('')}
        </select>` : '';
    const noteTitle = isDeputy() ? 'إضافة ملاحظة أو توجيه' : isDept() ? 'إضافة ملاحظة متابعة' : 'إضافة ملاحظة';

    const unassigned = S.departments.filter((d) => d.active && !(c.assignments || []).some((a) => a.department_id === d.id && a.status !== 'returned'));

    main.innerHTML = `
      ${r.q.sent ? `<div class="banner no-print"><span>✅ تم حفظ الشكوى وتحويلها. أرسل إشعاراً لمسؤول القسم عبر واتساب:</span>
        <div class="row">${(c.assignments || []).map((a) => `<a class="btn wa sm" target="_blank" rel="noopener" href="${esc(waUrl((S.deptMap[a.department_id] || {}).whatsapp, waDeptText(c)))}">💬 ${esc(deptName(a.department_id))}</a>`).join('')}</div></div>` : ''}
      <div class="row between mb no-print">
        <a href="#/list" class="btn gray sm">→ رجوع</a>
        <div class="row">
          ${isAdmin() ? `<a class="btn light sm" href="#/edit/${c.id}">✏️ تعديل</a>` : ''}
          <button class="btn light sm" onclick="window.print()">🖨️ طباعة</button>
        </div>
      </div>
      <div class="card ${late ? 'late' : ''}">
        <div class="c-head">
          <span class="c-serial" style="font-size:1.4rem">${esc(c.serial)}</span>
          ${prBadge(c.priority)} ${stBadge(st)} ${late ? '<span class="badge late">⏰ متأخرة</span>' : ''}
          ${c.source === 'whatsapp' ? '<span class="badge">وصلت تلقائياً من واتساب</span>' : ''}
          ${c.source === 'citizen' ? '<span class="badge src-citizen">👤 قدّمها المواطن عبر الموقع</span>' : ''}
        </div>
        ${reasons.length ? `<div class="err-box">${reasons.map(esc).join('<br>')}</div>` : ''}
        <div class="pre mt" style="font-size:1.08rem">${esc(c.body)}</div>
        <dl class="kv mt">
          <dt>تاريخ الورود</dt><dd>${esc(fmtDT(c.created_at))}</dd>
          ${c.area || c.address ? `<dt>المكان</dt><dd>📍 ${esc([c.area, c.address].filter(Boolean).join(' — '))}</dd>` : ''}
          ${c.citizen_name ? `<dt>المواطن</dt><dd>${esc(c.citizen_name)}</dd>` : ''}
          ${c.citizen_phone ? `<dt>الهاتف</dt><dd><a href="tel:${esc(c.citizen_phone)}" dir="ltr">${esc(c.citizen_phone)}</a></dd>` : ''}
          ${c.closed_at ? `<dt>أُقفلت</dt><dd>${esc(fmtDT(c.closed_at))} (المدة الكلية: ${esc(fmtDuration(new Date(c.closed_at) - new Date(c.created_at)))})</dd>` : ''}
          ${!isDept() ? `<dt>نائب الرئيس</dt><dd>${c.deputy_seen_at ? `<span class="badge deputy">👁️ اطّلع ${esc(fmtDT(c.deputy_seen_at))}</span>` : '<span class="badge unseen">لم يطّلع بعد</span>'}</dd>` : ''}
        </dl>
        ${mainAtts.length ? `<h3 class="mt">الصور والمرفقات</h3><div class="thumbs">${mainAtts.map(thumb).join('')}</div>` : ''}
        ${isAdmin() ? `<div class="row mt no-print">
            <button class="btn light sm" id="add-files">📎 إضافة مرفقات</button>
            ${c.citizen_phone ? `<a class="btn wa sm" target="_blank" rel="noopener" href="${esc(waUrl(c.citizen_phone, waCitizenText(c)))}">💬 إرسال النتيجة للمواطن</a>` : ''}
          </div>` : ''}
      </div>

      <div class="card">
        <h2>الأقسام المحوَّل إليها</h2>
        ${deptCards || '<div class="empty">لم تُحوَّل إلى أي قسم بعد</div>'}
        ${isAdmin() && unassigned.length ? `<div class="no-print mt">
            <label class="f">تحويل إلى قسم ${(c.assignments || []).length ? 'إضافي' : ''}</label>
            <div class="choices">${unassigned.map((d) => `<label class="choice"><input type="checkbox" name="as-dept" value="${esc(d.id)}"><span>${esc(d.name)}</span></label>`).join('')}</div>
            <button class="btn mt" id="as-btn">📤 تحويل</button>
          </div>` : ''}
      </div>

      <div class="card">
        <h2>الملاحظات والتوجيهات</h2>
        ${notesHtml || '<div class="muted">لا توجد ملاحظات بعد</div>'}
        <div class="no-print mt">
          <label class="f" for="nt-body">${esc(noteTitle)}</label>
          <textarea id="nt-body" placeholder="اكتب هنا…"></textarea>
          ${noteTargets}
          <button class="btn mt" id="nt-btn">إضافة</button>
        </div>
      </div>

      ${!isDept() && views.length ? `<div class="card"><h2>من فتح الشكوى</h2>
        <div class="table-wrap"><table class="t"><thead><tr><th>المستخدم</th><th>أول مشاهدة</th><th>آخر مشاهدة</th><th class="num">عدد المرات</th></tr></thead>
        <tbody>${views.map((v) => `<tr><td>${esc(userName(v.user_id))} <span class="muted small">(${esc(S.profiles[v.user_id] ? (S.profiles[v.user_id].role === 'department' ? deptName(S.profiles[v.user_id].department_id) : ROLE[S.profiles[v.user_id].role]) : '')})</span></td>
          <td>${esc(fmtDT(v.first_viewed_at))}</td><td>${esc(fmtDT(v.last_viewed_at))}</td><td class="num">${v.view_count}</td></tr>`).join('')}</tbody></table></div></div>` : ''}

      <div class="card">
        <h2>السجل الزمني</h2>
        <ul class="timeline">
          ${events.map((e) => `<li><div><b>${esc(e.action)}</b> — ${esc(e.actor_name)}</div>
            ${e.details ? `<div class="pre small">${esc(e.details)}</div>` : ''}
            <div class="when">${esc(fmtDT(e.created_at))}</div></li>`).join('')}
        </ul>
      </div>`;

    // ربط الأزرار
    const ta = document.getElementById('nt-body');
    ta.addEventListener('input', () => { S.dirty = ta.value.trim().length > 0; });
    document.getElementById('nt-btn').onclick = async (ev) => {
      const body = ta.value.trim();
      if (!body) { toast('اكتب الملاحظة أولاً', 'err'); return; }
      ev.target.disabled = true;
      try {
        const tgt = document.getElementById('nt-target');
        await rpc('add_note', { p_id: c.id, p_body: body, p_department: tgt ? tgt.value || null : null });
        S.dirty = false;
        toast('تمت إضافة الملاحظة', 'ok');
        render(true);
      } catch (e) { toast(errMsg(e), 'err'); ev.target.disabled = false; }
    };

    main.querySelectorAll('[data-act]').forEach((b) => {
      b.onclick = () => assignmentAction(c, b.dataset.act, Number(b.dataset.a));
    });

    const asBtn = document.getElementById('as-btn');
    if (asBtn) asBtn.onclick = async () => {
      const depts = [...main.querySelectorAll('input[name=as-dept]:checked')].map((i) => i.value);
      if (!depts.length) { toast('اختر قسماً', 'err'); return; }
      asBtn.disabled = true;
      try {
        await rpc('assign_departments', { p_id: c.id, p_departments: depts });
        toast('تم التحويل', 'ok');
        await loadComplaints();
        go('#/c/' + c.id + '?sent=1');
      } catch (e) { toast(errMsg(e), 'err'); asBtn.disabled = false; }
    };

    const addFiles = document.getElementById('add-files');
    if (addFiles) addFiles.onclick = () => pickFiles(async (files) => {
      toast('جارٍ رفع المرفقات…');
      await uploadFiles(c.id, files, 'complaint');
      render(true);
    });
  }

  function pickFiles(cb, accept) {
    const inp = document.createElement('input');
    inp.type = 'file';
    inp.multiple = true;
    inp.accept = accept || 'image/*,application/pdf,audio/*,video/*';
    inp.onchange = () => { if (inp.files.length) cb(inp.files); };
    inp.click();
  }

  // نافذة حوار عامة
  function dialog(html, onOk, okLabel, okClass) {
    $dlg.innerHTML = `<form method="dialog"><div class="dlg-body">${html}<div id="dlg-err" class="err-box hidden"></div></div>
      <div class="dlg-actions"><button class="btn ${okClass || ''}" value="ok" id="dlg-ok">${esc(okLabel || 'تأكيد')}</button>
      <button class="btn gray" value="cancel" formnovalidate>إلغاء</button></div></form>`;
    const form = $dlg.querySelector('form');
    form.onsubmit = async (ev) => {
      if (ev.submitter && ev.submitter.value === 'cancel') return;
      ev.preventDefault();
      const ok = document.getElementById('dlg-ok');
      const err = document.getElementById('dlg-err');
      ok.disabled = true;
      err.classList.add('hidden');
      try {
        await onOk($dlg);
        $dlg.close();
      } catch (e) {
        err.textContent = errMsg(e);
        err.classList.remove('hidden');
        ok.disabled = false;
      }
    };
    $dlg.showModal();
    const first = $dlg.querySelector('textarea, input');
    if (first) first.focus();
  }

  function assignmentAction(c, act, aid) {
    const a = (c.assignments || []).find((x) => x.id === aid);
    const dn = a ? deptName(a.department_id) : '';
    const after = async () => { await loadComplaints(); render(true); };

    if (act === 'remove') {
      if (!confirm('إلغاء تحويل الشكوى عن ' + dn + '؟')) return;
      rpc('remove_assignment', { p_assignment: aid }).then(() => { toast('تم إلغاء التحويل', 'ok'); after(); })
        .catch((e) => toast(errMsg(e), 'err'));
      return;
    }
    if (act === 'after') {
      pickFiles(async (files) => {
        toast('جارٍ رفع الصورة…');
        const failed = await uploadFiles(c.id, files, 'after');
        if (!failed) toast('تم إرفاق الصورة', 'ok');
        render(true);
      }, 'image/*');
      return;
    }
    if (act === 'req_approval' || act === 'approve' || act === 'reject') {
      const ac = {
        req_approval: { t: '🖊️ طلب موافقة نائب الرئيس — ' + dn, l: 'سبب طلب الموافقة * (مثال: تحتاج صرف مواد / قرار إداري)', ok: 'إرسال الطلب', cls: 'purple', req: true },
        approve: { t: '✅ الموافقة — ' + dn, l: 'ملاحظة أو توجيه (اختياري)', ok: 'موافقة', cls: 'ok', req: false },
        reject: { t: '❌ رفض الطلب — ' + dn, l: 'سبب الرفض * (إلزامي)', ok: 'رفض', cls: 'danger', req: true }
      }[act];
      dialog(`<h2>${esc(ac.t)}</h2>
        ${a && a.approval_reason && act !== 'req_approval' ? `<div class="approval-box pending"><b>سبب الطلب:</b> <span class="pre">${esc(a.approval_reason)}</span></div>` : ''}
        <label class="f" for="d-text">${esc(ac.l)}</label><textarea id="d-text" ${ac.req ? 'required minlength="3"' : ''}></textarea>`,
      async (d) => {
        const text = d.querySelector('#d-text').value.trim();
        if (ac.req && text.length < 3) throw new Error('هذا الحقل إلزامي');
        if (act === 'req_approval') await rpc('request_approval', { p_assignment: aid, p_reason: text });
        else await rpc('decide_approval', { p_assignment: aid, p_approve: act === 'approve', p_note: text });
        toast(act === 'req_approval' ? 'تم إرسال الطلب لنائب الرئيس' : 'تم تسجيل القرار', 'ok');
        after();
      }, ac.ok, ac.cls);
      return;
    }
    const conf = {
      in_progress: { t: '▶️ بدء المتابعة — ' + dn, l: 'ملاحظة المتابعة (اختياري)', req: false, ok: 'بدء المتابعة', cls: 'warn' },
      resolved: { t: '✅ تمت المعالجة — ' + dn, l: 'النتيجة النهائية * (إلزامي)', req: true, ok: 'إقفال: تمت المعالجة', cls: 'ok', photo: true },
      failed: { t: '⛔ تعذّرت المعالجة — ' + dn, l: 'سبب التعذّر * (إلزامي)', req: true, ok: 'إقفال: تعذّرت المعالجة', cls: 'danger' },
      returned: { t: '↩️ إعادة الشكوى إلى مسؤول الشكاوى', l: 'سبب الإعادة * (مثال: ليست من اختصاص القسم)', req: true, ok: 'إعادة', cls: 'gray' },
      reopen: { t: '🔄 إعادة فتح الشكوى لدى ' + dn, l: 'سبب إعادة الفتح *', req: true, ok: 'إعادة فتح', cls: '' }
    }[act];
    if (!conf) return;
    dialog(`<h2>${esc(conf.t)}</h2>
      <label class="f" for="d-text">${esc(conf.l)}</label>
      <textarea id="d-text" ${conf.req ? 'required minlength="3"' : ''}></textarea>
      ${conf.photo && isDept() ? '<label class="f" for="d-photo">📷 صورة بعد المعالجة (اختياري)</label><input type="file" id="d-photo" accept="image/*" multiple>' : ''}`,
    async (d) => {
      const text = d.querySelector('#d-text').value.trim();
      if (conf.req && text.length < 3) throw new Error('هذا الحقل إلزامي');
      if (act === 'reopen') await rpc('reopen_assignment', { p_assignment: aid, p_reason: text });
      else await rpc('update_assignment_status', { p_assignment: aid, p_status: act, p_text: text });
      const ph = d.querySelector('#d-photo');
      if (ph && ph.files.length) await uploadFiles(c.id, ph.files, 'after');
      toast('تم الحفظ', 'ok');
      after();
    }, conf.ok, conf.cls);
  }

  // ------------------------------------------------------------------
  // الإشعارات
  // ------------------------------------------------------------------
  async function viewNotifications(main) {
    const { data, error } = await sb.from('notifications').select('*').eq('user_id', S.me.id)
      .order('created_at', { ascending: false }).limit(200);
    if (error) throw error;
    const perm = 'Notification' in window ? Notification.permission : 'unsupported';
    main.innerHTML = `
      <div class="row between mb">
        <h1>🔔 الإشعارات</h1>
        <div class="row">
          <button class="btn light sm" id="n-read">✔️ تعليم الكل كمقروء</button>
        </div>
      </div>
      ${perm === 'default' ? `<div class="banner"><span>فعّل الإشعارات لتصلك التنبيهات على الهاتف أو الكمبيوتر.</span><button class="btn sm" id="n-perm">تفعيل الإشعارات</button></div>` : ''}
      ${perm === 'denied' ? `<div class="banner"><span>الإشعارات محظورة في المتصفح. فعّلها من إعدادات الموقع في المتصفح.</span></div>` : ''}
      ${data.length ? data.map((n) => `
        <a class="card notif ${n.read_at ? '' : 'unread'}" href="${n.complaint_id ? '#/c/' + n.complaint_id : '#/notifications'}" data-id="${n.id}">
          <span class="dot">${/تأخير/.test(n.title) ? '⏰' : '🔔'}</span>
          <div class="grow"><b>${esc(n.title)}</b><div class="small">${esc(n.body)}</div><div class="small muted">${esc(fmtDT(n.created_at))}</div></div>
        </a>`).join('') : '<div class="card empty">لا توجد إشعارات</div>'}`;
    main.querySelectorAll('.notif').forEach((el) => {
      el.addEventListener('click', () => {
        sb.from('notifications').update({ read_at: new Date().toISOString() }).eq('id', Number(el.dataset.id)).is('read_at', null)
          .then(loadUnread);
      });
    });
    document.getElementById('n-read').onclick = async () => {
      await sb.from('notifications').update({ read_at: new Date().toISOString() }).eq('user_id', S.me.id).is('read_at', null);
      await loadUnread();
      render(true);
    };
    const pb = document.getElementById('n-perm');
    if (pb) pb.onclick = async () => {
      const p = await Notification.requestPermission();
      if (p === 'granted') toast('تم تفعيل الإشعارات', 'ok');
      render(true);
    };
  }

  // ------------------------------------------------------------------
  // التقرير الشهري
  // ------------------------------------------------------------------
  async function viewReport(main, r) {
    if (isDept()) { main.innerHTML = '<div class="card">غير مسموح</div>'; return; }
    const now = new Date();
    const m = r.q.m || (now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0'));
    const [y, mo] = m.split('-').map(Number);
    const start = new Date(y, mo - 1, 1).getTime();
    const end = new Date(y, mo, 1).getTime();
    const list = S.complaints.filter((c) => { const t = new Date(c.created_at).getTime(); return t >= start && t < end; })
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    const monthName = new Intl.DateTimeFormat('ar-LB-u-nu-latn', { month: 'long', year: 'numeric' }).format(new Date(y, mo - 1, 1));

    const counts = Object.fromEntries(ST_ORDER.map((s) => [s, 0]));
    list.forEach((c) => counts[complaintStatus(c)]++);
    const late = list.filter(isLate).length;
    const byArea = {};
    list.forEach((c) => { const k = c.area || 'غير محدد'; byArea[k] = (byArea[k] || 0) + 1; });
    const byPr = { normal: 0, urgent: 0, emergency: 0 };
    list.forEach((c) => byPr[c.priority]++);

    const deptRows = S.departments.map((d) => {
      const as = [];
      list.forEach((c) => (c.assignments || []).forEach((a) => { if (a.department_id === d.id) as.push(a); }));
      const closed = as.filter((a) => a.closed_at && ['resolved', 'failed'].includes(a.status));
      const avg = closed.length ? closed.reduce((s, a) => s + (new Date(a.closed_at) - new Date(a.assigned_at)), 0) / closed.length : null;
      const cnt = (s) => as.filter((a) => a.status === s).length;
      const rate = as.length ? Math.round(cnt('resolved') * 100 / as.length) + '%' : '—';
      return `<tr><td><b>${esc(d.name)}</b></td><td class="num">${as.length}</td><td class="num">${cnt('resolved')}</td>
        <td class="num">${cnt('failed')}</td><td class="num">${cnt('new') + cnt('seen') + cnt('in_progress')}</td>
        <td class="num">${cnt('returned')}</td><td class="num">${as.filter((a) => lateInfo(a).any).length}</td>
        <td class="num">${esc(fmtDuration(avg))}</td><td class="num">${rate}</td></tr>`;
    }).join('');

    main.innerHTML = `
      <div class="row between mb no-print">
        <h1>🖨️ التقرير الشهري</h1>
        <div class="row">
          <input type="month" id="rp-m" value="${esc(m)}" style="width:auto">
          <button class="btn" onclick="window.print()">🖨️ طباعة / حفظ PDF</button>
          <button class="btn light" id="rp-x">📊 Excel</button>
        </div>
      </div>
      <div class="report">
        <img src="icons/logo.png" alt="" style="display:block;width:90px;height:90px;margin:0 auto 6px">
        <h1>${esc(S.settings.municipality_name)}</h1>
        <div class="sub">تقرير شكاوى المواطنين — ${esc(monthName)}<br>تاريخ الإصدار: ${esc(fmtDT(new Date()))}</div>
        <div class="grid stats mb">
          <div class="stat"><div class="num">${list.length}</div><div class="lbl">مجموع الشكاوى</div></div>
          <div class="stat st-resolved"><div class="num">${counts.resolved}</div><div class="lbl">تمت المعالجة</div></div>
          <div class="stat st-failed"><div class="num">${counts.failed}</div><div class="lbl">تعذّرت المعالجة</div></div>
          <div class="stat st-in_progress"><div class="num">${counts.new + counts.seen + counts.in_progress + counts.returned + counts.pending}</div><div class="lbl">ما زالت مفتوحة</div></div>
          <div class="stat late"><div class="num">${late}</div><div class="lbl">متأخرة حالياً</div></div>
        </div>
        <div class="card"><h2>حسب الأقسام</h2><div class="table-wrap"><table class="t">
          <thead><tr><th>القسم</th><th class="num">المحوَّلة</th><th class="num">عولجت</th><th class="num">تعذّرت</th><th class="num">مفتوحة</th><th class="num">أُعيدت</th><th class="num">متأخرة</th><th class="num">متوسط المعالجة</th><th class="num">نسبة المعالجة</th></tr></thead>
          <tbody>${deptRows}</tbody></table></div></div>
        <div class="grid two">
          <div class="card"><h2>حسب المنطقة</h2><table class="t"><tbody>
            ${Object.entries(byArea).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join('') || '<tr><td>—</td></tr>'}
          </tbody></table></div>
          <div class="card"><h2>حسب الأولوية</h2><table class="t"><tbody>
            ${Object.entries(byPr).map(([k, v]) => `<tr><td>${esc(PR[k])}</td><td class="num">${v}</td></tr>`).join('')}
          </tbody></table></div>
        </div>
        <div class="card"><h2>قائمة الشكاوى</h2><div class="table-wrap"><table class="t">
          <thead><tr><th>الرقم</th><th>التاريخ</th><th>المنطقة</th><th>الشكوى</th><th>القسم والحالة</th><th>النتيجة</th></tr></thead>
          <tbody>${list.map((c) => `<tr><td>${esc(c.serial)}</td><td>${esc(fmtD(c.created_at))}</td><td>${esc(c.area)}</td>
            <td>${esc(c.body.length > 140 ? c.body.slice(0, 140) + '…' : c.body)}</td>
            <td>${(c.assignments || []).map((a) => esc(deptName(a.department_id) + ': ' + ST[a.status])).join('<br>')}</td>
            <td>${(c.assignments || []).filter((a) => a.result).map((a) => esc(a.result)).join('<br>')}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">لا توجد شكاوى في هذا الشهر</td></tr>'}
          </tbody></table></div></div>
        <div class="row mt" style="justify-content:space-around;margin-top:40px">
          <div>توقيع مسؤول الشكاوى: ..................</div><div>توقيع نائب الرئيس: ..................</div>
        </div>
      </div>`;
    document.getElementById('rp-m').onchange = (e) => go('#/report?m=' + e.target.value);
    document.getElementById('rp-x').onclick = () => exportExcel(list, 'تقرير ' + m);
  }

  // ------------------------------------------------------------------
  // الإعدادات (المستخدمون، الأقسام، المناطق، المدد، النسخ الاحتياطي)
  // ------------------------------------------------------------------
  async function viewSettings(main) {
    const myPass = `
      <div class="card">
        <h2>🔑 تغيير كلمة السر الخاصة بي</h2>
        <form id="pw-form" class="row">
          <input type="password" id="pw-new" placeholder="كلمة السر الجديدة (6 أحرف على الأقل)" minlength="6" required class="grow" style="max-width:360px" dir="ltr">
          <button class="btn" type="submit">حفظ</button>
        </form>
      </div>`;
    if (!isAdmin()) {
      main.innerHTML = `<h1>حسابي</h1>
        <div class="card"><dl class="kv"><dt>الاسم</dt><dd>${esc(S.me.full_name)}</dd><dt>اسم الدخول</dt><dd dir="ltr">${esc(S.me.username)}</dd>
        <dt>الصفة</dt><dd>${esc(isDept() ? deptName(S.me.department_id) : ROLE[S.me.role])}</dd></dl></div>${myPass}
        <button class="btn danger block" id="lo2">🚪 تسجيل الخروج</button>`;
      bindMyPass();
      document.getElementById('lo2').onclick = logout;
      return;
    }
    await loadRefData();
    const users = Object.values(S.profiles);
    const deptOpts = (sel) => S.departments.map((d) => `<option value="${esc(d.id)}" ${d.id === sel ? 'selected' : ''}>${esc(d.name)}</option>`).join('');

    main.innerHTML = `
      <h1>⚙️ الإعدادات</h1>

      <div class="card">
        <div class="row between"><h2>👥 المستخدمون</h2><button class="btn" id="u-add">➕ مستخدم جديد</button></div>
        <div class="table-wrap"><table class="t">
          <thead><tr><th>الاسم</th><th>اسم الدخول</th><th>الصفة</th><th>الهاتف</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${users.map((u) => `<tr>
            <td><b>${esc(u.full_name)}</b></td><td dir="ltr" style="text-align:right">${esc(u.username)}</td>
            <td>${esc(u.role === 'department' ? deptName(u.department_id) : ROLE[u.role])}</td>
            <td dir="ltr" style="text-align:right">${esc(u.phone)}</td>
            <td>${u.active ? '<span class="badge st-resolved">فعّال</span>' : '<span class="badge st-failed">معطّل</span>'}</td>
            <td><div class="row"><button class="btn light sm" data-edit="${u.id}">تعديل</button><button class="btn gray sm" data-pass="${u.id}">كلمة السر</button></div></td>
          </tr>`).join('')}</tbody></table></div>
      </div>

      <div class="card">
        <h2>🏢 الأقسام وأرقام واتساب</h2>
        <p class="muted small">رقم واتساب مسؤول القسم يُستعمل لزر "إرسال عبر واتساب". مثال: 03123456 أو 71123456</p>
        <div class="table-wrap"><table class="t"><thead><tr><th>اسم القسم</th><th>رقم واتساب المسؤول</th><th>فعّال</th><th></th></tr></thead>
        <tbody>${S.departments.map((d) => `<tr data-dept="${esc(d.id)}">
          <td><input type="text" class="d-name" value="${esc(d.name)}"></td>
          <td><input type="tel" class="d-wa" dir="ltr" value="${esc(d.whatsapp)}" placeholder="03123456"></td>
          <td><input type="checkbox" class="d-active" ${d.active ? 'checked' : ''} style="width:24px;height:24px"></td>
          <td><button class="btn sm d-save">حفظ</button></td></tr>`).join('')}</tbody></table></div>
        <form class="row mt" id="d-add"><input type="text" id="d-new" placeholder="اسم قسم جديد" class="grow" style="max-width:320px" required><button class="btn light">➕ إضافة قسم</button></form>
      </div>

      <div class="card">
        <h2>📍 المناطق والأحياء</h2>
        <div class="choices">${S.areas.map((a) => `<span class="dept-chip">${esc(a.name)} <button class="btn gray sm" data-del-area="${a.id}" style="min-height:30px;padding:2px 8px">✖</button></span>`).join('')}</div>
        <form class="row mt" id="a-add"><input type="text" id="a-new" placeholder="اسم منطقة جديدة" class="grow" style="max-width:320px" required><button class="btn light">➕ إضافة</button></form>
      </div>

      <div class="card">
        <h2>⏰ مدد التأخير والإعدادات العامة</h2>
        <form id="s-form" class="grid two">
          <div><label class="f">اسم البلدية</label><input type="text" id="s-name" value="${esc(S.settings.municipality_name)}" required></div>
          <div><label class="f">تُعتبر متأخرة إذا لم تُشاهد خلال (ساعة)</label><input type="number" id="s-h" min="1" value="${S.settings.unseen_hours}" required></div>
          <div><label class="f">تُعتبر متأخرة إذا لم تُعالج خلال (يوم)</label><input type="number" id="s-d" min="1" value="${S.settings.unresolved_days}" required></div>
          <div><label class="f">&nbsp;</label><button class="btn block">💾 حفظ الإعدادات</button></div>
        </form>
      </div>

      <div class="card">
        <h2>💾 النسخ الاحتياطي</h2>
        <p>نزّل نسخة كاملة من كل البيانات واحفظها على الكمبيوتر أو Google Drive. يُنصح بذلك مرة في الأسبوع على الأقل (إضافة إلى النسخ التلقائي اليومي إن فعّلته).</p>
        <div class="row">
          <button class="btn" id="b-json">⬇️ تنزيل نسخة احتياطية كاملة (JSON)</button>
          <button class="btn light" id="b-xlsx">📊 تنزيل كل الشكاوى (Excel)</button>
        </div>
      </div>
      ${myPass}`;

    bindMyPass();

    main.querySelectorAll('[data-edit]').forEach((b) => { b.onclick = () => userDialog(S.profiles[b.dataset.edit]); });
    main.querySelectorAll('[data-pass]').forEach((b) => {
      b.onclick = () => {
        const u = S.profiles[b.dataset.pass];
        dialog(`<h2>تغيير كلمة سر: ${esc(u.full_name)}</h2>
          <label class="f">كلمة السر الجديدة</label><input type="text" id="up-pass" dir="ltr" minlength="6" required>`,
        async (d) => {
          await rpc('admin_set_password', { p_id: u.id, p_password: d.querySelector('#up-pass').value });
          toast('تم تغيير كلمة السر', 'ok');
        }, 'حفظ');
      };
    });
    document.getElementById('u-add').onclick = () => userDialog(null);

    function userDialog(u) {
      const isNew = !u;
      u = u || { full_name: '', username: '', role: 'department', department_id: S.departments[0] && S.departments[0].id, phone: '', active: true };
      dialog(`<h2>${isNew ? 'مستخدم جديد' : 'تعديل: ' + esc(u.full_name)}</h2>
        <label class="f">الاسم الكامل</label><input type="text" id="u-name" value="${esc(u.full_name)}" required>
        ${isNew ? `<label class="f">اسم الدخول (أحرف إنكليزية وأرقام)</label><input type="text" id="u-user" dir="ltr" autocapitalize="none" required pattern="[a-zA-Z0-9._-]{3,30}">
          <label class="f">كلمة السر (6 أحرف على الأقل)</label><input type="text" id="u-pass" dir="ltr" minlength="6" required>` : ''}
        <label class="f">الصفة</label>
        <select id="u-role">
          <option value="department" ${u.role === 'department' ? 'selected' : ''}>موظف قسم</option>
          <option value="deputy" ${u.role === 'deputy' ? 'selected' : ''}>نائب الرئيس</option>
          <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>مسؤول الشكاوى</option>
        </select>
        <div id="u-dept-wrap"><label class="f">القسم</label><select id="u-dept">${deptOpts(u.department_id)}</select></div>
        <label class="f">الهاتف (اختياري)</label><input type="tel" id="u-phone" dir="ltr" value="${esc(u.phone)}">
        ${isNew ? '' : `<label class="check-row mt"><input type="checkbox" id="u-active" ${u.active ? 'checked' : ''}> الحساب فعّال</label>`}`,
      async (d) => {
        const role = d.querySelector('#u-role').value;
        const dept = role === 'department' ? d.querySelector('#u-dept').value : null;
        if (isNew) {
          await rpc('admin_create_user', {
            p_username: d.querySelector('#u-user').value, p_password: d.querySelector('#u-pass').value,
            p_full_name: d.querySelector('#u-name').value, p_role: role, p_department: dept, p_phone: d.querySelector('#u-phone').value
          });
          toast('تم إنشاء المستخدم', 'ok');
        } else {
          await rpc('admin_update_user', {
            p_id: u.id, p_full_name: d.querySelector('#u-name').value, p_role: role, p_department: dept,
            p_phone: d.querySelector('#u-phone').value, p_active: d.querySelector('#u-active').checked
          });
          toast('تم الحفظ', 'ok');
        }
        render(true);
      }, 'حفظ');
      const roleSel = $dlg.querySelector('#u-role');
      const toggle = () => $dlg.querySelector('#u-dept-wrap').classList.toggle('hidden', roleSel.value !== 'department');
      roleSel.onchange = toggle; toggle();
    }

    main.querySelectorAll('tr[data-dept]').forEach((tr) => {
      tr.querySelector('.d-save').onclick = async () => {
        const { error } = await sb.from('departments').update({
          name: tr.querySelector('.d-name').value.trim(),
          whatsapp: tr.querySelector('.d-wa').value.trim(),
          active: tr.querySelector('.d-active').checked
        }).eq('id', tr.dataset.dept);
        if (error) toast(errMsg(error), 'err'); else { toast('تم الحفظ', 'ok'); await loadRefData(); }
      };
    });
    document.getElementById('d-add').onsubmit = async (e) => {
      e.preventDefault();
      const name = document.getElementById('d-new').value.trim();
      const { error } = await sb.from('departments').insert({ id: 'd' + Date.now().toString(36), name, sort: S.departments.length + 1 });
      if (error) toast(errMsg(error), 'err'); else { toast('تمت إضافة القسم', 'ok'); render(true); }
    };
    main.querySelectorAll('[data-del-area]').forEach((b) => {
      b.onclick = async () => {
        if (!confirm('حذف هذه المنطقة من القائمة؟ (لن تتأثر الشكاوى السابقة)')) return;
        const { error } = await sb.from('areas').delete().eq('id', Number(b.dataset.delArea));
        if (error) toast(errMsg(error), 'err'); else render(true);
      };
    });
    document.getElementById('a-add').onsubmit = async (e) => {
      e.preventDefault();
      const { error } = await sb.from('areas').insert({ name: document.getElementById('a-new').value.trim(), sort: S.areas.length + 1 });
      if (error) toast(errMsg(error), 'err'); else render(true);
    };
    document.getElementById('s-form').onsubmit = async (e) => {
      e.preventDefault();
      const { error } = await sb.from('app_settings').update({
        municipality_name: document.getElementById('s-name').value.trim(),
        unseen_hours: Number(document.getElementById('s-h').value),
        unresolved_days: Number(document.getElementById('s-d').value),
        updated_at: new Date().toISOString()
      }).eq('id', 1);
      if (error) toast(errMsg(error), 'err'); else { toast('تم حفظ الإعدادات', 'ok'); await loadRefData(); }
    };
    document.getElementById('b-json').onclick = backupJson;
    document.getElementById('b-xlsx').onclick = () => exportExcel(S.complaints, 'كل الشكاوى');
  }

  function bindMyPass() {
    document.getElementById('pw-form').onsubmit = async (e) => {
      e.preventDefault();
      const { error } = await sb.auth.updateUser({ password: document.getElementById('pw-new').value });
      if (error) toast(errMsg(error), 'err');
      else { toast('تم تغيير كلمة السر', 'ok'); document.getElementById('pw-new').value = ''; }
    };
  }

  async function backupJson() {
    toast('جارٍ تجهيز النسخة الاحتياطية…');
    try {
      const tables = ['app_settings', 'departments', 'areas', 'profiles', 'complaints', 'assignments', 'notes', 'events', 'attachments', 'complaint_views'];
      const out = { created_at: new Date().toISOString(), app: 'harethreik-complaints', tables: {} };
      for (const t of tables) out.tables[t] = await fetchAll(() => sb.from(t).select('*'));
      const blob = new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'نسخة-احتياطية-الشكاوى-' + new Date().toISOString().slice(0, 10) + '.json';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      toast('تم تنزيل النسخة الاحتياطية', 'ok');
    } catch (e) { toast(errMsg(e), 'err'); }
  }

  // ------------------------------------------------------------------
  // التشغيل
  // ------------------------------------------------------------------
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
  }
  // إعادة فحص التأخير كل 10 دقائق لتحديث الألوان
  setInterval(() => { if (S.me && !S.dirty) { const r = parseRoute(); if (r.name === 'dashboard' || r.name === 'list') render(true); } }, 600000);

  sb.auth.onAuthStateChange((event) => {
    if (event === 'SIGNED_OUT' && S.me) { S.me = null; viewLogin(); }
  });

  start();
})();
