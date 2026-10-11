-- =====================================================================
--  الملف 3: تحديث - صفحة المواطنين + موافقة نائب الرئيس
--  طريقة الاستعمال: انسخه كاملاً في Supabase > SQL Editor > New query ثم Run
--  آمن: لا يحذف أي بيانات، ويمكن تشغيله أكثر من مرة.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) تعديلات الجداول
-- ---------------------------------------------------------------------
alter table public.complaints drop constraint if exists complaints_source_check;
alter table public.complaints add constraint complaints_source_check
  check (source in ('manual', 'whatsapp', 'citizen'));
alter table public.complaints add column if not exists upload_token uuid;

alter table public.assignments add column if not exists approval_status text not null default 'none';
alter table public.assignments drop constraint if exists assignments_approval_status_check;
alter table public.assignments add constraint assignments_approval_status_check
  check (approval_status in ('none', 'pending', 'approved', 'rejected'));
alter table public.assignments add column if not exists approval_requested_at timestamptz;
alter table public.assignments add column if not exists approval_requested_by uuid references public.profiles(id);
alter table public.assignments add column if not exists approval_reason text;
alter table public.assignments add column if not exists approval_decided_at timestamptz;
alter table public.assignments add column if not exists approval_decided_by uuid references public.profiles(id);
alter table public.assignments add column if not exists approval_note text;

-- مفتاح الهاتف: آخر 7 أرقام (لمقارنة الأرقام بغض النظر عن الصيغة)
create or replace function public._phone_key(p text) returns text
language sql immutable as $$
  select right(regexp_replace(coalesce(p, ''), '\D', '', 'g'), 7)
$$;

-- ---------------------------------------------------------------------
-- 2) موافقة نائب الرئيس
-- ---------------------------------------------------------------------

-- القسم يطلب موافقة نائب الرئيس
create or replace function public.request_approval(p_assignment bigint, p_reason text) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles; a public.assignments; c public.complaints; t text := trim(coalesce(p_reason, ''));
begin
  me := public._me();
  select * into a from public.assignments where id = p_assignment for update;
  if a.id is null then raise exception 'التحويل غير موجود'; end if;
  if not (me.role = 'admin' or (me.role = 'department' and me.department_id = a.department_id)) then
    raise exception 'غير مسموح';
  end if;
  if a.status not in ('new', 'seen', 'in_progress') then raise exception 'الشكوى مقفلة لدى القسم'; end if;
  if a.approval_status = 'pending' then raise exception 'طلب الموافقة مُرسل سابقاً وبانتظار الرد'; end if;
  if length(t) < 3 then raise exception 'يجب ذكر سبب طلب الموافقة'; end if;
  select * into c from public.complaints where id = a.complaint_id;

  update public.assignments set approval_status = 'pending', approval_requested_at = now(), approval_requested_by = me.id,
    approval_reason = t, approval_decided_at = null, approval_decided_by = null, approval_note = null,
    seen_at = coalesce(seen_at, now()), seen_by = coalesce(seen_by, me.id),
    status = case when status = 'new' then 'seen' else status end
   where id = a.id;
  perform public._log(a.complaint_id, a.department_id, 'طلب موافقة نائب الرئيس', public._dept_name(a.department_id) || ': ' || t);
  perform public._notify_role('deputy', a.complaint_id, 'مطلوب موافقتك — شكوى ' || c.serial,
    public._dept_name(a.department_id) || ': ' || left(t, 150));
  perform public._notify_role('admin', a.complaint_id, 'طلب موافقة نائب الرئيس — شكوى ' || c.serial,
    public._dept_name(a.department_id) || ': ' || left(t, 150));
end $$;

-- نائب الرئيس يوافق أو يرفض
create or replace function public.decide_approval(p_assignment bigint, p_approve boolean, p_note text) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles; a public.assignments; c public.complaints; t text := trim(coalesce(p_note, '')); label text;
begin
  me := public._me();
  if me.role <> 'deputy' then raise exception 'الموافقة من صلاحية نائب الرئيس فقط'; end if;
  select * into a from public.assignments where id = p_assignment for update;
  if a.id is null then raise exception 'التحويل غير موجود'; end if;
  if a.approval_status <> 'pending' then raise exception 'لا يوجد طلب موافقة معلّق'; end if;
  if not p_approve and length(t) < 3 then raise exception 'يجب ذكر سبب الرفض'; end if;
  select * into c from public.complaints where id = a.complaint_id;

  update public.assignments set approval_status = case when p_approve then 'approved' else 'rejected' end,
    approval_decided_at = now(), approval_decided_by = me.id, approval_note = nullif(t, '')
   where id = a.id;
  update public.complaints set deputy_seen_at = coalesce(deputy_seen_at, now()), deputy_seen_by = coalesce(deputy_seen_by, me.id)
   where id = a.complaint_id;
  label := case when p_approve then 'وافق نائب الرئيس' else 'رفض نائب الرئيس' end;
  perform public._log(a.complaint_id, a.department_id, label,
    public._dept_name(a.department_id) || case when t <> '' then ': ' || t else '' end);
  perform public._notify_dept(a.department_id, a.complaint_id, label || ' — شكوى ' || c.serial, coalesce(nullif(t, ''), label));
  perform public._notify_role('admin', a.complaint_id, label || ' — شكوى ' || c.serial,
    public._dept_name(a.department_id) || case when t <> '' then ': ' || left(t, 150) else '' end);
end $$;

-- تحديث: منع إقفال الشكوى بينما طلب الموافقة معلّق
create or replace function public.update_assignment_status(p_assignment bigint, p_status text, p_text text)
returns void language plpgsql security definer set search_path = public as $$
declare me public.profiles; a public.assignments; c public.complaints; t text := trim(coalesce(p_text, ''));
        label text;
begin
  me := public._me();
  select * into a from public.assignments where id = p_assignment for update;
  if a.id is null then raise exception 'التحويل غير موجود'; end if;
  if not (me.role = 'admin' or (me.role = 'department' and me.department_id = a.department_id)) then
    raise exception 'غير مسموح: هذه الشكوى ليست من اختصاص قسمك';
  end if;
  if a.status in ('resolved', 'failed', 'returned') then
    raise exception 'هذه الشكوى مقفلة لدى القسم. يمكن لمسؤول الشكاوى إعادة فتحها';
  end if;
  if a.approval_status = 'pending' and p_status in ('resolved', 'failed') then
    raise exception 'لا يمكن الإقفال: الشكوى بانتظار موافقة نائب الرئيس';
  end if;
  select * into c from public.complaints where id = a.complaint_id;

  if p_status = 'in_progress' then
    if a.status = 'in_progress' then raise exception 'الشكوى قيد المتابعة أصلاً'; end if;
    update public.assignments set status = 'in_progress', started_at = now(),
      seen_at = coalesce(seen_at, now()), seen_by = coalesce(seen_by, me.id)
     where id = a.id;
    label := 'بدء المتابعة';
    if t <> '' then
      insert into public.notes (complaint_id, department_id, author_id, kind, body)
      values (a.complaint_id, a.department_id, me.id, 'followup', t);
    end if;
  elsif p_status in ('resolved', 'failed', 'returned') then
    if length(t) < 3 then
      raise exception '%', case p_status when 'resolved' then 'يجب كتابة النتيجة قبل إقفال الشكوى'
                                        when 'failed' then 'يجب ذكر سبب تعذّر المعالجة'
                                        else 'يجب ذكر سبب الإعادة' end;
    end if;
    if p_status = 'returned' and me.role <> 'department' then raise exception 'غير مسموح'; end if;
    update public.assignments set status = p_status, closed_at = now(), closed_by = me.id, result = t,
      seen_at = coalesce(seen_at, now()), seen_by = coalesce(seen_by, me.id),
      approval_status = case when approval_status = 'pending' then 'none' else approval_status end
     where id = a.id;
    label := case p_status when 'resolved' then 'تمت المعالجة'
                           when 'failed' then 'تعذّرت المعالجة'
                           else 'أُعيدت إلى مسؤول الشكاوى' end;
    perform public._notify_role('admin', a.complaint_id,
      label || ' — شكوى ' || c.serial, public._dept_name(a.department_id) || ': ' || left(t, 150));
  else
    raise exception 'حالة غير معروفة';
  end if;

  perform public._log(a.complaint_id, a.department_id, label, public._dept_name(a.department_id) ||
                      case when t <> '' then ': ' || t else '' end);
  perform public._refresh_complaint_state(a.complaint_id);
end $$;

-- ---------------------------------------------------------------------
-- 3) صفحة المواطنين (بدون تسجيل دخول)
-- ---------------------------------------------------------------------

-- تقديم شكوى من المواطن
create or replace function public.citizen_submit(
  p_name text, p_phone text, p_area text, p_address text, p_body text, p_website text default ''
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare ns record; cid bigint; tok uuid := gen_random_uuid(); k text := public._phone_key(p_phone);
        b text := trim(coalesce(p_body, ''));
begin
  if coalesce(p_website, '') <> '' then raise exception 'تعذّر الإرسال'; end if;   -- فخ للبرامج الآلية
  if coalesce(trim(p_name), '') = '' then raise exception 'يرجى كتابة الاسم'; end if;
  if length(k) < 7 then raise exception 'يرجى كتابة رقم هاتف صحيح'; end if;
  if length(b) < 10 then raise exception 'يرجى كتابة تفاصيل الشكوى (10 أحرف على الأقل)'; end if;
  if length(b) > 5000 then raise exception 'نص الشكوى طويل جداً'; end if;
  if (select count(*) from public.complaints
       where source = 'citizen' and public._phone_key(citizen_phone) = k and created_at > now() - interval '1 day') >= 3 then
    raise exception 'لقد أرسلت 3 شكاوى اليوم. يرجى المحاولة غداً أو التواصل مع البلدية مباشرة';
  end if;
  if (select count(*) from public.complaints where source = 'citizen' and created_at > now() - interval '1 hour') >= 60 then
    raise exception 'الخدمة مشغولة حالياً، يرجى المحاولة بعد قليل';
  end if;

  select * into ns from public._next_serial();
  insert into public.complaints (serial, year, seq, body, citizen_name, citizen_phone, area, address, source, upload_token)
  values (ns.serial, ns.y, ns.s, b, left(trim(p_name), 120), left(trim(p_phone), 30),
          left(coalesce(trim(p_area), ''), 120), left(coalesce(trim(p_address), ''), 300), 'citizen', tok)
  returning id into cid;
  insert into public.events (complaint_id, actor_name, action, details)
  values (cid, 'المواطن: ' || left(trim(p_name), 120), 'شكوى مقدّمة من المواطن عبر الموقع', left(trim(p_phone), 30));
  insert into public.notifications (user_id, complaint_id, title, body)
  select id, cid, 'شكوى جديدة من مواطن ' || ns.serial || ' — بانتظار التحويل', left(b, 150)
    from public.profiles where role = 'admin' and active;
  return jsonb_build_object('id', cid, 'serial', ns.serial, 'token', tok);
end $$;

-- هل يحق للمواطن رفع هذا الملف؟ (خلال 30 دقيقة من الإرسال، 5 ملفات كحد أقصى)
create or replace function public.citizen_can_upload(p_path text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.complaints c
     where c.id = public.path_complaint_id(p_path)
       and c.source = 'citizen'
       and c.upload_token::text = split_part(p_path, '/', 2)
       and c.created_at > now() - interval '30 minutes')
  and (select count(*) from public.attachments a where a.complaint_id = public.path_complaint_id(p_path)) < 5
$$;

create or replace function public.citizen_add_attachment(p_id bigint, p_path text, p_name text, p_mime text, p_size int)
returns void language plpgsql security definer set search_path = public as $$
begin
  if public.path_complaint_id(p_path) is distinct from p_id or not public.citizen_can_upload(p_path) then
    raise exception 'غير مسموح';
  end if;
  insert into public.attachments (complaint_id, kind, path, file_name, mime, size)
  values (p_id, 'complaint', p_path, left(coalesce(p_name, ''), 200), left(coalesce(p_mime, ''), 100), coalesce(p_size, 0))
  on conflict (path) do nothing;
end $$;

-- متابعة حالة الشكوى (برقم الشكوى ورقم الهاتف) - يُظهر الحالة والنتيجة فقط
create or replace function public.citizen_track(p_serial text, p_phone text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare c public.complaints; st text; results jsonb;
begin
  select * into c from public.complaints
   where serial = trim(p_serial) and public._phone_key(citizen_phone) = public._phone_key(p_phone)
     and length(public._phone_key(p_phone)) >= 7;
  if c.id is null then return null; end if;
  if c.closed_at is not null then
    st := case when exists (select 1 from public.assignments where complaint_id = c.id and status = 'resolved')
               then 'تمت المعالجة' else 'تعذّرت المعالجة' end;
  elsif not exists (select 1 from public.assignments where complaint_id = c.id and status <> 'returned') then
    st := 'قيد المراجعة لدى البلدية';
  elsif exists (select 1 from public.assignments where complaint_id = c.id and status in ('in_progress')) then
    st := 'قيد المتابعة';
  else
    st := 'تم تحويلها إلى الدائرة المختصة';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object('department', d.name, 'status', a.status, 'result', a.result) order by a.id), '[]'::jsonb)
    into results
    from public.assignments a join public.departments d on d.id = a.department_id
   where a.complaint_id = c.id and a.status in ('resolved', 'failed');
  return jsonb_build_object('serial', c.serial, 'created_at', c.created_at, 'closed_at', c.closed_at,
                            'status', st, 'results', results);
end $$;

-- ---------------------------------------------------------------------
-- 4) الصلاحيات
-- ---------------------------------------------------------------------
revoke execute on function public.citizen_submit(text, text, text, text, text, text) from public;
revoke execute on function public.citizen_add_attachment(bigint, text, text, text, int) from public;
revoke execute on function public.citizen_track(text, text) from public;
revoke execute on function public.citizen_can_upload(text) from public;
grant execute on function public.citizen_submit(text, text, text, text, text, text) to anon, authenticated;
grant execute on function public.citizen_add_attachment(bigint, text, text, text, int) to anon, authenticated;
grant execute on function public.citizen_track(text, text) to anon, authenticated;
grant execute on function public.citizen_can_upload(text) to anon, authenticated;
grant execute on function public.path_complaint_id(text) to anon;
grant execute on function public._phone_key(text) to anon, authenticated;
revoke execute on function public.request_approval(bigint, text) from public, anon;
revoke execute on function public.decide_approval(bigint, boolean, text) from public, anon;
grant execute on function public.request_approval(bigint, text) to authenticated;
grant execute on function public.decide_approval(bigint, boolean, text) to authenticated;
grant execute on function public.update_assignment_status(bigint, text, text) to authenticated;

-- المواطن يرفع صوراً لشكواه فقط، خلال 30 دقيقة من إرسالها
drop policy if exists "citizen files upload" on storage.objects;
create policy "citizen files upload" on storage.objects for insert to anon
  with check (bucket_id = 'attachments' and public.citizen_can_upload(name));

-- انتهى التحديث

-- قائمة المناطق تظهر في صفحة المواطن
grant select on public.areas to anon;
drop policy if exists areas_public on public.areas;
create policy areas_public on public.areas for select to anon using (true);
