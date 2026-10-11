/* صفحة المواطنين: تقديم شكوى ومتابعتها فقط (بدون تسجيل دخول) */
(function () {
  'use strict';
  const CFG = window.APP_CONFIG || {};
  // جلسة منفصلة دائماً كزائر، حتى لو كان أحد الموظفين مسجّلاً على نفس الجهاز
  const sb = window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY, {
    auth: { persistSession: false, autoRefreshToken: false, storageKey: 'citizen-page' }
  });
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const fmtDT = (d) => (d ? new Intl.DateTimeFormat('ar-LB-u-nu-latn', { timeZone: 'Asia/Beirut', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(d)) : '');
  const errMsg = (e) => {
    const m = (e && e.message) || String(e || '');
    if (/Failed to fetch|NetworkError/i.test(m)) return 'لا يوجد اتصال بالإنترنت، حاول مجدداً';
    return m || 'حدث خطأ، حاول مجدداً';
  };
  function toast(msg, type) {
    const el = document.createElement('div');
    el.className = 'toast ' + (type || '');
    el.textContent = msg;
    $('toasts').appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  // التبويبات
  function show(tab) {
    $('tab-new').classList.toggle('on', tab === 'new');
    $('tab-track').classList.toggle('on', tab === 'track');
    $('f-new').classList.toggle('hidden', tab !== 'new');
    $('done').classList.add('hidden');
    $('f-track').classList.toggle('hidden', tab !== 'track');
  }
  $('tab-new').onclick = () => show('new');
  $('tab-track').onclick = () => show('track');
  if (location.hash === '#track') show('track');

  // المناطق
  sb.from('areas').select('name').order('sort').order('name').then(({ data }) => {
    (data || []).forEach((a) => {
      const o = document.createElement('option');
      o.textContent = a.name;
      $('c-area').appendChild(o);
    });
  });

  // معاينة الصور
  $('c-files').onchange = () => {
    const files = [...$('c-files').files].slice(0, 5);
    if ($('c-files').files.length > 5) toast('يمكن إرفاق 5 صور كحد أقصى', 'err');
    $('c-preview').innerHTML = '';
    files.forEach((f) => {
      const img = document.createElement('img');
      img.src = URL.createObjectURL(f);
      $('c-preview').appendChild(img);
    });
  };

  function compressImage(file) {
    return new Promise((resolve) => {
      if (!/^image\//i.test(file.type)) return resolve(file);
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const max = 1600;
        let w = img.width, h = img.height;
        if (w > max || h > max) { const k = max / Math.max(w, h); w = Math.round(w * k); h = Math.round(h * k); }
        const cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        cv.getContext('2d').drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        cv.toBlob((b) => resolve(b ? new File([b], 'photo.jpg', { type: 'image/jpeg' }) : file), 'image/jpeg', 0.8);
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }

  // إرسال الشكوى
  $('f-new').onsubmit = async (ev) => {
    ev.preventDefault();
    const btn = $('c-send');
    const err = $('c-err');
    err.classList.add('hidden');
    btn.disabled = true;
    btn.textContent = 'جارٍ الإرسال…';
    try {
      const { data, error } = await sb.rpc('citizen_submit', {
        p_name: $('c-name').value, p_phone: $('c-phone').value, p_area: $('c-area').value,
        p_address: $('c-addr').value, p_body: $('c-body').value, p_website: $('c-website').value
      });
      if (error) throw error;
      const files = [...$('c-files').files].filter((f) => /^image\//.test(f.type)).slice(0, 5);
      let failed = 0;
      for (let i = 0; i < files.length; i++) {
        btn.textContent = 'جارٍ رفع الصور (' + (i + 1) + '/' + files.length + ')…';
        try {
          const f = await compressImage(files[i]);
          if (f.size > 10 * 1024 * 1024) { failed++; continue; }
          const path = data.id + '/' + data.token + '/' + Date.now() + '-' + i + '.jpg';
          const up = await sb.storage.from('attachments').upload(path, f, { contentType: f.type || 'image/jpeg' });
          if (up.error) throw up.error;
          const r = await sb.rpc('citizen_add_attachment', { p_id: data.id, p_path: path, p_name: files[i].name, p_mime: f.type, p_size: f.size });
          if (r.error) throw r.error;
        } catch (e) { failed++; }
      }
      if (failed) toast('تم إرسال الشكوى، لكن تعذّر رفع ' + failed + ' صورة', 'err');
      $('f-new').reset();
      $('c-preview').innerHTML = '';
      $('done-serial').textContent = data.serial;
      $('t-serial').value = data.serial;
      $('f-new').classList.add('hidden');
      $('done').classList.remove('hidden');
      window.scrollTo(0, 0);
    } catch (e) {
      err.textContent = errMsg(e);
      err.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.textContent = '📨 إرسال الشكوى';
    }
  };

  $('done-again').onclick = () => show('new');
  $('done-copy').onclick = async () => {
    try { await navigator.clipboard.writeText($('done-serial').textContent); toast('تم نسخ الرقم', 'ok'); }
    catch (e) { toast('انسخ الرقم يدوياً: ' + $('done-serial').textContent); }
  };

  // متابعة الشكوى
  $('f-track').onsubmit = async (ev) => {
    ev.preventDefault();
    const out = $('t-out');
    const btn = $('t-btn');
    btn.disabled = true;
    out.innerHTML = '<div class="spinner">جارٍ البحث…</div>';
    try {
      const serial = $('t-serial').value.trim().replace(/\s/g, '');
      const { data, error } = await sb.rpc('citizen_track', { p_serial: serial, p_phone: $('t-phone').value });
      if (error) throw error;
      if (!data) {
        out.innerHTML = '<div class="err-box">لم نجد شكوى بهذا الرقم ورقم الهاتف. تأكّد من الرقمين وحاول مجدداً.</div>';
        return;
      }
      const done = !!data.closed_at;
      out.innerHTML = `
        <div class="card" style="margin:0">
          <div class="c-head"><span class="c-serial">${esc(data.serial)}</span>
            <span class="badge ${done ? (data.status === 'تمت المعالجة' ? 'st-resolved' : 'st-failed') : 'st-in_progress'}">${esc(data.status)}</span></div>
          <div class="small muted">تاريخ التقديم: ${esc(fmtDT(data.created_at))}</div>
          ${done ? `<div class="small muted">تاريخ الإنجاز: ${esc(fmtDT(data.closed_at))}</div>` : ''}
          ${(data.results || []).map((r) => `<div class="result-box ${r.status}"><b>${r.status === 'resolved' ? 'النتيجة' : 'ملاحظة'}${data.results.length > 1 ? ' — ' + esc(r.department) : ''}:</b>
            <div class="pre">${esc(r.result)}</div></div>`).join('')}
          ${done ? '' : '<p class="small">شكواكم قيد المتابعة، وسنعمل على معالجتها في أقرب وقت.</p>'}
        </div>`;
    } catch (e) {
      out.innerHTML = '<div class="err-box">' + esc(errMsg(e)) + '</div>';
    } finally {
      btn.disabled = false;
    }
  };
})();
