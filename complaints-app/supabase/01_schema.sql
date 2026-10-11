-- =====================================================================
--  نظام إدارة شكاوى المواطنين - بلدية حارة حريك
--  الملف 1 من 2: بنية قاعدة البيانات والصلاحيات
--  طريقة الاستعمال: انسخ هذا الملف كاملاً والصقه في Supabase > SQL Editor ثم اضغط Run
--  يمكن إعادة تشغيله لاحقاً بأمان (لتحديث الدوال) دون حذف البيانات.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------
-- 1) الجداول
-- ---------------------------------------------------------------------

-- إعدادات عامة (صف واحد فقط)
create table if not exists public.app_settings (
  id               int primary key default 1 check (id = 1),
  municipality_name text not null default 'بلدية حارة حريك',
  unseen_hours     int  not null default 24 check (unseen_hours > 0),
  unresolved_days  int  not null default 7  check (unresolved_days > 0),
  login_domain     text not null default 'harethreik.app',
  updated_at       timestamptz not null default now()
);
insert into public.app_settings (id) values (1) on conflict (id) do nothing;

-- الأقسام
create table if not exists public.departments (
  id        text primary key,
  name      text not null unique,
  whatsapp  text not null default '',
  color     text not null default '#2563eb',
  sort      int  not null default 0,
  active    boolean not null default true
);
insert into public.departments (id, name, color, sort) values
  ('works',  'دائرة الأشغال',  '#d97706', 1),
  ('health', 'المفرزة الصحية', '#059669', 2),
  ('police', 'دائرة الشرطة',   '#2563eb', 3)
on conflict (id) do nothing;

-- المناطق والأحياء (قابلة للتعديل من شاشة الإعدادات)
create table if not exists public.areas (
  id    serial primary key,
  name  text not null unique,
  sort  int  not null default 0
);
insert into public.areas (name, sort) values
  ('المعمورة', 1), ('صفير', 2), ('بئر العبد', 3), ('الرويس', 4),
  ('حي الأميركان', 5), ('السانت تيريز', 6), ('الكفاءات', 7), ('وسط حارة حريك', 8), ('أخرى', 99)
on conflict (name) do nothing;

-- المستخدمون (مرتبطون بحسابات الدخول في auth.users)
create table if not exists public.profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  username      text not null unique,
  full_name     text not null,
  role          text not null check (role in ('admin', 'department', 'deputy')),
  department_id text references public.departments(id),
  phone         text not null default '',
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  constraint profiles_role_dept check ((role = 'department') = (department_id is not null))
);

-- الشكاوى
create table if not exists public.complaints (
  id             bigserial primary key,
  serial         text not null unique,
  year           int  not null,
  seq            int  not null,
  body           text not null,
  citizen_name   text not null default '',
  citizen_phone  text not null default '',
  area           text not null default '',
  address        text not null default '',
  priority       text not null default 'normal' check (priority in ('normal', 'urgent', 'emergency')),
  source         text not null default 'manual' check (source in ('manual', 'whatsapp')),
  source_ref     text unique,                     -- رقم رسالة واتساب عند الربط التلقائي لاحقاً
  created_by     uuid references public.profiles(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  closed_at      timestamptz,                     -- تُملأ تلقائياً عندما تنهي كل الأقسام عملها
  deputy_seen_at timestamptz,
  deputy_seen_by uuid references public.profiles(id),
  unique (year, seq)
);
create index if not exists complaints_created_at_idx on public.complaints (created_at desc);

-- تحويل الشكوى إلى قسم (شكوى واحدة قد تُحوَّل إلى أكثر من قسم، ولكل قسم حالته)
create table if not exists public.assignments (
  id                bigserial primary key,
  complaint_id      bigint not null references public.complaints(id) on delete cascade,
  department_id     text   not null references public.departments(id),
  status            text   not null default 'new'
                    check (status in ('new', 'seen', 'in_progress', 'resolved', 'failed', 'returned')),
  assigned_at       timestamptz not null default now(),
  assigned_by       uuid references public.profiles(id),
  seen_at           timestamptz,
  seen_by           uuid references public.profiles(id),
  started_at        timestamptz,
  closed_at         timestamptz,
  closed_by         uuid references public.profiles(id),
  result            text,          -- النتيجة النهائية أو سبب التعذّر أو سبب الإعادة
  unseen_alerted_at timestamptz,
  overdue_alerted_at timestamptz,
  unique (complaint_id, department_id)
);
create index if not exists assignments_dept_idx on public.assignments (department_id, status);

-- سجل المشاهدات (كل مستخدم فتح الشكوى)
create table if not exists public.complaint_views (
  complaint_id    bigint not null references public.complaints(id) on delete cascade,
  user_id         uuid   not null references public.profiles(id) on delete cascade,
  first_viewed_at timestamptz not null default now(),
  last_viewed_at  timestamptz not null default now(),
  view_count      int not null default 1,
  primary key (complaint_id, user_id)
);

-- الملاحظات والتوجيهات
create table if not exists public.notes (
  id            bigserial primary key,
  complaint_id  bigint not null references public.complaints(id) on delete cascade,
  department_id text references public.departments(id),   -- فارغ = ملاحظة عامة
  author_id     uuid references public.profiles(id),
  kind          text not null check (kind in ('followup', 'directive', 'admin')),
  body          text not null,
  created_at    timestamptz not null default now()
);

-- المرفقات (الصور والملفات)
create table if not exists public.attachments (
  id            bigserial primary key,
  complaint_id  bigint not null references public.complaints(id) on delete cascade,
  department_id text references public.departments(id),   -- معبّأ لصور "بعد المعالجة"
  kind          text not null default 'complaint' check (kind in ('complaint', 'after')),
  path          text not null unique,
  file_name     text not null default '',
  mime          text not null default '',
  size          int  not null default 0,
  uploaded_by   uuid references public.profiles(id),
  created_at    timestamptz not null default now()
);

-- السجل الزمني: من فعل ماذا ومتى
create table if not exists public.events (
  id            bigserial primary key,
  complaint_id  bigint not null references public.complaints(id) on delete cascade,
  department_id text references public.departments(id),
  actor_id      uuid references public.profiles(id),
  actor_name    text not null default '',
  action        text not null,
  details       text not null default '',
  internal      boolean not null default false,  -- يظهر فقط للمسؤول ونائب الرئيس
  created_at    timestamptz not null default now()
);
create index if not exists events_complaint_idx on public.events (complaint_id, created_at);

-- الإشعارات داخل التطبيق
create table if not exists public.notifications (
  id           bigserial primary key,
  user_id      uuid not null references public.profiles(id) on delete cascade,
  complaint_id bigint references public.complaints(id) on delete cascade,
  title        text not null,
  body         text not null default '',
  read_at      timestamptz,
  created_at   timestamptz not null default now()
);
create index if not exists notifications_user_idx on public.notifications (user_id, created_at desc);

-- ---------------------------------------------------------------------
-- 2) دوال مساعدة
-- ---------------------------------------------------------------------

create or replace function public.my_role() returns text
language sql stable security definer set search_path = public as $$
  select role from public.profiles where id = auth.uid() and active
$$;

create or replace function public.my_dept() returns text
language sql stable security definer set search_path = public as $$
  select department_id from public.profiles where id = auth.uid() and active
$$;

create or replace function public.can_see_complaint(cid bigint) returns boolean
language sql stable security definer set search_path = public as $$
  select case public.my_role()
    when 'admin'  then true
    when 'deputy' then true
    when 'department' then exists (
      select 1 from public.assignments a
      where a.complaint_id = cid and a.department_id = public.my_dept())
    else false end
$$;

-- يستخرج رقم الشكوى من مسار الملف في التخزين (مثال: 15/abc.jpg)
create or replace function public.path_complaint_id(p text) returns bigint
language sql immutable as $$
  select case when split_part(p, '/', 1) ~ '^[0-9]+$' then split_part(p, '/', 1)::bigint else null end
$$;

create or replace function public._me() returns public.profiles
language plpgsql stable security definer set search_path = public as $$
declare r public.profiles;
begin
  select * into r from public.profiles where id = auth.uid() and active;
  if r.id is null then raise exception 'غير مسموح: يجب تسجيل الدخول'; end if;
  return r;
end $$;

create or replace function public._log(cid bigint, dept text, act text, det text default '', is_internal boolean default false)
returns void language plpgsql security definer set search_path = public as $$
declare uname text;
begin
  select full_name into uname from public.profiles where id = auth.uid();
  insert into public.events (complaint_id, department_id, actor_id, actor_name, action, details, internal)
  values (cid, dept, auth.uid(), coalesce(uname, 'النظام'), act, coalesce(det, ''), is_internal);
end $$;

create or replace function public._notify_role(r text, cid bigint, t text, b text) returns void
language sql security definer set search_path = public as $$
  insert into public.notifications (user_id, complaint_id, title, body)
  select id, cid, t, b from public.profiles
  where role = r and active and id is distinct from auth.uid()
$$;

create or replace function public._notify_dept(dept text, cid bigint, t text, b text) returns void
language sql security definer set search_path = public as $$
  insert into public.notifications (user_id, complaint_id, title, body)
  select id, cid, t, b from public.profiles
  where role = 'department' and department_id = dept and active and id is distinct from auth.uid()
$$;

create or replace function public._dept_name(dept text) returns text
language sql stable security definer set search_path = public as $$
  select name from public.departments where id = dept
$$;

-- تُقفل الشكوى عندما لا يبقى أي قسم قيد العمل
create or replace function public._refresh_complaint_state(cid bigint) returns void
language plpgsql security definer set search_path = public as $$
declare open_count int; total int;
begin
  select count(*) filter (where status in ('new', 'seen', 'in_progress', 'returned')), count(*)
    into open_count, total from public.assignments where complaint_id = cid;
  update public.complaints
     set closed_at = case when total > 0 and open_count = 0 then coalesce(closed_at, now()) else null end,
         updated_at = now()
   where id = cid;
end $$;

create or replace function public._next_serial(out y int, out s int, out serial text)
language plpgsql security definer set search_path = public as $$
begin
  y := extract(year from (now() at time zone 'Asia/Beirut'))::int;
  perform pg_advisory_xact_lock(778800 + y);
  select coalesce(max(seq), 0) + 1 into s from public.complaints where year = y;
  serial := y::text || '-' || lpad(s::text, 4, '0');
end $$;

-- ---------------------------------------------------------------------
-- 3) العمليات (كل التعديلات تمر من هنا مع التحقق من الصلاحيات)
-- ---------------------------------------------------------------------

-- إنشاء شكوى جديدة (مسؤول الشكاوى فقط)
create or replace function public.create_complaint(
  p_body text, p_citizen_name text, p_citizen_phone text, p_area text, p_address text,
  p_priority text, p_departments text[]
) returns public.complaints
language plpgsql security definer set search_path = public as $$
declare me public.profiles; c public.complaints; ns record; d text;
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'فقط مسؤول الشكاوى يمكنه إدخال شكوى'; end if;
  if coalesce(trim(p_body), '') = '' then raise exception 'نص الشكوى مطلوب'; end if;
  select * into ns from public._next_serial();
  insert into public.complaints (serial, year, seq, body, citizen_name, citizen_phone, area, address, priority, created_by)
  values (ns.serial, ns.y, ns.s, trim(p_body), coalesce(trim(p_citizen_name), ''), coalesce(trim(p_citizen_phone), ''),
          coalesce(trim(p_area), ''), coalesce(trim(p_address), ''), coalesce(p_priority, 'normal'), me.id)
  returning * into c;
  perform public._log(c.id, null, 'إنشاء الشكوى', 'رقم ' || c.serial);
  if p_departments is not null and array_length(p_departments, 1) > 0 then
    perform public.assign_departments(c.id, p_departments);
  end if;
  return c;
end $$;

-- تعديل بيانات الشكوى (مسؤول الشكاوى فقط)
create or replace function public.update_complaint(
  p_id bigint, p_body text, p_citizen_name text, p_citizen_phone text, p_area text, p_address text, p_priority text
) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles;
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'غير مسموح'; end if;
  if coalesce(trim(p_body), '') = '' then raise exception 'نص الشكوى مطلوب'; end if;
  update public.complaints set body = trim(p_body), citizen_name = coalesce(trim(p_citizen_name), ''),
    citizen_phone = coalesce(trim(p_citizen_phone), ''), area = coalesce(trim(p_area), ''),
    address = coalesce(trim(p_address), ''), priority = p_priority, updated_at = now()
  where id = p_id;
  perform public._log(p_id, null, 'تعديل بيانات الشكوى', '');
end $$;

-- تحويل الشكوى إلى قسم أو أكثر
create or replace function public.assign_departments(p_id bigint, p_departments text[]) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles; d text; c public.complaints; added text[] := '{}';
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'فقط مسؤول الشكاوى يمكنه التحويل'; end if;
  select * into c from public.complaints where id = p_id;
  if c.id is null then raise exception 'الشكوى غير موجودة'; end if;
  foreach d in array p_departments loop
    if not exists (select 1 from public.departments where id = d) then raise exception 'قسم غير معروف: %', d; end if;
    if exists (select 1 from public.assignments where complaint_id = p_id and department_id = d and status <> 'returned') then
      continue;
    end if;
    insert into public.assignments (complaint_id, department_id, assigned_by)
    values (p_id, d, me.id)
    on conflict (complaint_id, department_id) do update
      set status = 'new', assigned_at = now(), assigned_by = me.id, seen_at = null, seen_by = null,
          started_at = null, closed_at = null, closed_by = null, result = null,
          unseen_alerted_at = null, overdue_alerted_at = null;
    added := added || public._dept_name(d);
    perform public._notify_dept(d, p_id, 'شكوى جديدة رقم ' || c.serial,
      left(c.body, 120) || case when c.area <> '' then ' — ' || c.area else '' end);
  end loop;
  if array_length(added, 1) > 0 then
    perform public._log(p_id, null, 'تحويل الشكوى', 'إلى: ' || array_to_string(added, '، '));
  end if;
  perform public._refresh_complaint_state(p_id);
end $$;

-- إلغاء تحويل الشكوى عن قسم
create or replace function public.remove_assignment(p_assignment bigint) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles; a public.assignments;
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'غير مسموح'; end if;
  delete from public.assignments where id = p_assignment returning * into a;
  if a.id is null then return; end if;
  perform public._log(a.complaint_id, null, 'إلغاء التحويل', 'عن: ' || public._dept_name(a.department_id));
  perform public._refresh_complaint_state(a.complaint_id);
end $$;

-- تسجيل المشاهدة تلقائياً عند فتح الشكوى
create or replace function public.mark_viewed(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles; first_time boolean; n int;
begin
  me := public._me();
  if not public.can_see_complaint(p_id) then raise exception 'غير مسموح'; end if;

  insert into public.complaint_views (complaint_id, user_id) values (p_id, me.id)
  on conflict (complaint_id, user_id) do update
    set last_viewed_at = now(), view_count = complaint_views.view_count + 1;

  if me.role = 'department' then
    update public.assignments set status = 'seen', seen_at = now(), seen_by = me.id
     where complaint_id = p_id and department_id = me.department_id and status = 'new';
    get diagnostics n = row_count;
    if n > 0 then
      perform public._log(p_id, me.department_id, 'تمت المشاهدة', public._dept_name(me.department_id));
    end if;
  elsif me.role = 'deputy' then
    update public.complaints set deputy_seen_at = now(), deputy_seen_by = me.id
     where id = p_id and deputy_seen_at is null;
    get diagnostics n = row_count;
    if n > 0 then
      perform public._log(p_id, null, 'اطّلع عليها نائب الرئيس', '', true);
    end if;
  end if;
end $$;

-- تغيير حالة الشكوى لدى القسم
--   p_status: in_progress | resolved | failed | returned
--   p_text  : ملاحظة المتابعة / النتيجة النهائية / سبب التعذّر / سبب الإعادة
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
      seen_at = coalesce(seen_at, now()), seen_by = coalesce(seen_by, me.id)
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

-- إعادة فتح شكوى مقفلة لدى قسم (مسؤول الشكاوى فقط)
create or replace function public.reopen_assignment(p_assignment bigint, p_reason text) returns void
language plpgsql security definer set search_path = public as $$
declare me public.profiles; a public.assignments; c public.complaints;
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'غير مسموح'; end if;
  if length(trim(coalesce(p_reason, ''))) < 3 then raise exception 'يجب ذكر سبب إعادة الفتح'; end if;
  update public.assignments set status = 'in_progress', closed_at = null, closed_by = null,
    started_at = coalesce(started_at, now()), overdue_alerted_at = null
   where id = p_assignment returning * into a;
  if a.id is null then raise exception 'التحويل غير موجود'; end if;
  select * into c from public.complaints where id = a.complaint_id;
  perform public._log(a.complaint_id, a.department_id, 'إعادة فتح', public._dept_name(a.department_id) || ': ' || trim(p_reason));
  perform public._notify_dept(a.department_id, a.complaint_id, 'أُعيد فتح الشكوى ' || c.serial, trim(p_reason));
  perform public._refresh_complaint_state(a.complaint_id);
end $$;

-- إضافة ملاحظة
--   القسم: ملاحظة متابعة خاصة بقسمه
--   نائب الرئيس: توجيه (p_department فارغ = لكل الأقسام المعنية)
--   المسؤول: ملاحظة لقسم معيّن، أو ملاحظة داخلية إذا كان p_department فارغاً
create or replace function public.add_note(p_id bigint, p_body text, p_department text default null)
returns void language plpgsql security definer set search_path = public as $$
declare me public.profiles; c public.complaints; k text; dept text := nullif(p_department, ''); t text := trim(coalesce(p_body, ''));
        title text; d record;
begin
  me := public._me();
  if t = '' then raise exception 'نص الملاحظة فارغ'; end if;
  if not public.can_see_complaint(p_id) then raise exception 'غير مسموح'; end if;
  select * into c from public.complaints where id = p_id;

  if me.role = 'department' then
    k := 'followup'; dept := me.department_id;
  elsif me.role = 'deputy' then
    k := 'directive';
  else
    k := 'admin';
  end if;
  if dept is not null and not exists (select 1 from public.assignments where complaint_id = p_id and department_id = dept) then
    raise exception 'الشكوى غير محوّلة إلى هذا القسم';
  end if;

  insert into public.notes (complaint_id, department_id, author_id, kind, body) values (p_id, dept, me.id, k, t);

  if k = 'followup' then
    perform public._log(p_id, dept, 'ملاحظة متابعة', public._dept_name(dept) || ': ' || t);
    perform public._notify_role('admin', p_id, 'ملاحظة متابعة — شكوى ' || c.serial, public._dept_name(dept) || ': ' || left(t, 150));
  elsif k = 'directive' then
    perform public._log(p_id, dept, 'توجيه من نائب الرئيس', t);
    title := 'توجيه من نائب الرئيس — شكوى ' || c.serial;
    perform public._notify_role('admin', p_id, title, left(t, 150));
    for d in select department_id from public.assignments
             where complaint_id = p_id and (dept is null or department_id = dept) loop
      perform public._notify_dept(d.department_id, p_id, title, left(t, 150));
    end loop;
  else
    perform public._log(p_id, dept, case when dept is null then 'ملاحظة داخلية' else 'ملاحظة من مسؤول الشكاوى' end,
                        t, dept is null);
    if dept is not null then
      perform public._notify_dept(dept, p_id, 'ملاحظة من مسؤول الشكاوى — شكوى ' || c.serial, left(t, 150));
    end if;
  end if;
end $$;

-- تسجيل مرفق بعد رفعه إلى التخزين
create or replace function public.add_attachment(p_id bigint, p_path text, p_name text, p_mime text, p_size int, p_kind text)
returns void language plpgsql security definer set search_path = public as $$
declare me public.profiles; dept text;
begin
  me := public._me();
  if public.path_complaint_id(p_path) is distinct from p_id then raise exception 'مسار غير صالح'; end if;
  if me.role = 'admin' then
    dept := null;
  elsif me.role = 'department' and public.can_see_complaint(p_id) then
    dept := me.department_id;
  else
    raise exception 'غير مسموح';
  end if;
  insert into public.attachments (complaint_id, department_id, kind, path, file_name, mime, size, uploaded_by)
  values (p_id, dept, case when p_kind = 'after' then 'after' else 'complaint' end, p_path, coalesce(p_name, ''),
          coalesce(p_mime, ''), coalesce(p_size, 0), me.id);
  perform public._log(p_id, dept, case when p_kind = 'after' then 'إرفاق صورة بعد المعالجة' else 'إضافة مرفق' end, coalesce(p_name, ''));
end $$;

-- فحص التأخير وإرسال التنبيهات (يعمل تلقائياً كل ساعة، ويُستدعى أيضاً عند فتح لوحة التحكم)
create or replace function public.check_overdue() returns int
language plpgsql security definer set search_path = public as $$
declare s public.app_settings; r record; n int := 0;
begin
  select * into s from public.app_settings where id = 1;
  for r in
    update public.assignments a set unseen_alerted_at = now()
     where a.status = 'new' and a.unseen_alerted_at is null
       and a.assigned_at < now() - make_interval(hours => s.unseen_hours)
    returning a.complaint_id, a.department_id
  loop
    insert into public.notifications (user_id, complaint_id, title, body)
    select p.id, r.complaint_id, 'تأخير: شكوى لم تُشاهد — ' || c.serial,
           public._dept_name(r.department_id) || ' لم يفتح الشكوى خلال ' || s.unseen_hours || ' ساعة'
      from public.profiles p, public.complaints c
     where c.id = r.complaint_id and p.active
       and (p.role = 'admin' or (p.role = 'department' and p.department_id = r.department_id));
    n := n + 1;
  end loop;
  for r in
    update public.assignments a set overdue_alerted_at = now()
     where a.status in ('new', 'seen', 'in_progress') and a.overdue_alerted_at is null
       and a.assigned_at < now() - make_interval(days => s.unresolved_days)
    returning a.complaint_id, a.department_id
  loop
    insert into public.notifications (user_id, complaint_id, title, body)
    select p.id, r.complaint_id, 'تأخير: شكوى لم تُعالج — ' || c.serial,
           public._dept_name(r.department_id) || ' لم يُنهِ الشكوى خلال ' || s.unresolved_days || ' أيام'
      from public.profiles p, public.complaints c
     where c.id = r.complaint_id and p.active
       and (p.role = 'admin' or (p.role = 'department' and p.department_id = r.department_id));
    n := n + 1;
  end loop;
  return n;
end $$;

-- ---------------------------------------------------------------------
-- 4) إدارة المستخدمين (مسؤول الشكاوى فقط) - كلمات السر تُشفَّر بـ bcrypt
-- ---------------------------------------------------------------------

create or replace function public._create_auth_user(p_username text, p_password text) returns uuid
language plpgsql security definer set search_path = public, extensions as $$
declare uid uuid := gen_random_uuid(); em text; dom text;
begin
  select login_domain into dom from public.app_settings where id = 1;
  em := lower(trim(p_username)) || '@' || dom;
  insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, recovery_token, email_change_token_new, email_change)
  values ('00000000-0000-0000-0000-000000000000', uid, 'authenticated', 'authenticated', em,
    extensions.crypt(p_password, extensions.gen_salt('bf')), now(),
    '{"provider":"email","providers":["email"]}'::jsonb, jsonb_build_object('username', lower(trim(p_username))),
    now(), now(), '', '', '', '');
  insert into auth.identities (id, provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
  values (gen_random_uuid(), uid::text, uid,
    jsonb_build_object('sub', uid::text, 'email', em, 'email_verified', true), 'email', now(), now(), now());
  return uid;
end $$;

create or replace function public.admin_create_user(
  p_username text, p_password text, p_full_name text, p_role text, p_department text, p_phone text
) returns uuid language plpgsql security definer set search_path = public as $$
declare me public.profiles; uid uuid; u text := lower(trim(coalesce(p_username, '')));
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'غير مسموح'; end if;
  if u !~ '^[a-z0-9._-]{3,30}$' then
    raise exception 'اسم الدخول يجب أن يكون بالأحرف الإنكليزية أو الأرقام (3 أحرف على الأقل)';
  end if;
  if length(coalesce(p_password, '')) < 6 then raise exception 'كلمة السر يجب أن تكون 6 أحرف على الأقل'; end if;
  if exists (select 1 from public.profiles where username = u) then raise exception 'اسم الدخول مستعمل'; end if;
  if p_role not in ('admin', 'department', 'deputy') then raise exception 'دور غير صالح'; end if;
  uid := public._create_auth_user(u, p_password);
  insert into public.profiles (id, username, full_name, role, department_id, phone)
  values (uid, u, trim(p_full_name), p_role, case when p_role = 'department' then p_department end, coalesce(trim(p_phone), ''));
  return uid;
end $$;

create or replace function public.admin_update_user(
  p_id uuid, p_full_name text, p_role text, p_department text, p_phone text, p_active boolean
) returns void language plpgsql security definer set search_path = public as $$
declare me public.profiles;
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'غير مسموح'; end if;
  if p_id = me.id and (not p_active or p_role <> 'admin') then
    raise exception 'لا يمكنك تعطيل حسابك أو تغيير دورك';
  end if;
  update public.profiles set full_name = trim(p_full_name), role = p_role,
    department_id = case when p_role = 'department' then p_department end,
    phone = coalesce(trim(p_phone), ''), active = p_active
  where id = p_id;
  update auth.users set banned_until = case when p_active then null else 'infinity'::timestamptz end,
    updated_at = now() where id = p_id;
end $$;

create or replace function public.admin_set_password(p_id uuid, p_password text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare me public.profiles;
begin
  me := public._me();
  if me.role <> 'admin' then raise exception 'غير مسموح'; end if;
  if length(coalesce(p_password, '')) < 6 then raise exception 'كلمة السر يجب أن تكون 6 أحرف على الأقل'; end if;
  update auth.users set encrypted_password = extensions.crypt(p_password, extensions.gen_salt('bf')), updated_at = now()
  where id = p_id;
end $$;

-- ---------------------------------------------------------------------
-- 5) جاهز للربط لاحقاً مع WhatsApp Business API
--    تُستدعى من الخادم فقط (Edge Function بمفتاح service_role) - راجع ملف whatsapp-webhook
-- ---------------------------------------------------------------------
create or replace function public.ingest_whatsapp_message(p_phone text, p_name text, p_body text, p_message_id text)
returns bigint language plpgsql security definer set search_path = public as $$
declare ns record; cid bigint;
begin
  select id into cid from public.complaints where source_ref = p_message_id;
  if cid is not null then return cid; end if;  -- الرسالة مسجّلة سابقاً
  select * into ns from public._next_serial();
  insert into public.complaints (serial, year, seq, body, citizen_name, citizen_phone, source, source_ref)
  values (ns.serial, ns.y, ns.s, coalesce(p_body, ''), coalesce(p_name, ''), coalesce(p_phone, ''), 'whatsapp', p_message_id)
  returning id into cid;
  insert into public.events (complaint_id, actor_name, action, details)
  values (cid, 'واتساب', 'استلام تلقائي من واتساب', coalesce(p_phone, ''));
  insert into public.notifications (user_id, complaint_id, title, body)
  select id, cid, 'شكوى جديدة من واتساب ' || ns.serial || ' — بانتظار التحويل', left(coalesce(p_body, ''), 150)
    from public.profiles where role = 'admin' and active;
  return cid;
end $$;

-- ---------------------------------------------------------------------
-- 6) حماية البيانات (Row Level Security): كل قسم يرى شكاواه فقط
-- ---------------------------------------------------------------------

alter table public.app_settings    enable row level security;
alter table public.departments     enable row level security;
alter table public.areas           enable row level security;
alter table public.profiles        enable row level security;
alter table public.complaints      enable row level security;
alter table public.assignments     enable row level security;
alter table public.complaint_views enable row level security;
alter table public.notes           enable row level security;
alter table public.attachments     enable row level security;
alter table public.events          enable row level security;
alter table public.notifications   enable row level security;

-- لا شيء للزوار غير المسجّلين
revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;
-- المستخدم المسجّل يقرأ فقط (حسب السياسات)، وكل التعديلات تمر عبر الدوال أعلاه
revoke insert, update, delete, truncate on all tables in schema public from authenticated;
grant select on all tables in schema public to authenticated;
grant update (municipality_name, unseen_hours, unresolved_days, updated_at) on public.app_settings to authenticated;
grant insert, update, delete on public.departments, public.areas to authenticated;
grant usage on all sequences in schema public to authenticated;
grant update (read_at) on public.notifications to authenticated;
grant delete on public.notifications to authenticated;

drop policy if exists settings_read on public.app_settings;
create policy settings_read on public.app_settings for select to authenticated using (public.my_role() is not null);
drop policy if exists settings_write on public.app_settings;
create policy settings_write on public.app_settings for update to authenticated
  using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

drop policy if exists departments_read on public.departments;
create policy departments_read on public.departments for select to authenticated using (public.my_role() is not null);
drop policy if exists departments_write on public.departments;
create policy departments_write on public.departments for all to authenticated
  using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

drop policy if exists areas_read on public.areas;
create policy areas_read on public.areas for select to authenticated using (public.my_role() is not null);
drop policy if exists areas_write on public.areas;
create policy areas_write on public.areas for all to authenticated
  using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles for select to authenticated
  using (id = auth.uid() or public.my_role() is not null);

drop policy if exists complaints_read on public.complaints;
create policy complaints_read on public.complaints for select to authenticated
  using (public.can_see_complaint(id));

drop policy if exists assignments_read on public.assignments;
create policy assignments_read on public.assignments for select to authenticated
  using (public.my_role() in ('admin', 'deputy') or department_id = public.my_dept());

drop policy if exists views_read on public.complaint_views;
create policy views_read on public.complaint_views for select to authenticated
  using (public.my_role() in ('admin', 'deputy') or user_id = auth.uid());

drop policy if exists notes_read on public.notes;
create policy notes_read on public.notes for select to authenticated
  using (public.my_role() in ('admin', 'deputy')
         or (public.can_see_complaint(complaint_id)
             and (department_id = public.my_dept() or (department_id is null and kind = 'directive'))));

drop policy if exists attachments_read on public.attachments;
create policy attachments_read on public.attachments for select to authenticated
  using (public.my_role() in ('admin', 'deputy')
         or (public.can_see_complaint(complaint_id) and (department_id is null or department_id = public.my_dept())));

drop policy if exists events_read on public.events;
create policy events_read on public.events for select to authenticated
  using (public.my_role() in ('admin', 'deputy')
         or (public.can_see_complaint(complaint_id) and not internal
             and (department_id is null or department_id = public.my_dept())));

drop policy if exists notifications_own on public.notifications;
create policy notifications_own on public.notifications for select to authenticated using (user_id = auth.uid());
drop policy if exists notifications_update on public.notifications;
create policy notifications_update on public.notifications for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists notifications_delete on public.notifications;
create policy notifications_delete on public.notifications for delete to authenticated using (user_id = auth.uid());

-- صلاحيات تنفيذ الدوال
revoke execute on all functions in schema public from public, anon;
grant execute on all functions in schema public to authenticated;
revoke execute on function public.ingest_whatsapp_message(text, text, text, text) from authenticated;
revoke execute on function public._create_auth_user(text, text) from authenticated;
revoke execute on function public._notify_role(text, bigint, text, text) from authenticated;
revoke execute on function public._notify_dept(text, bigint, text, text) from authenticated;
revoke execute on function public._log(bigint, text, text, text, boolean) from authenticated;
revoke execute on function public._refresh_complaint_state(bigint) from authenticated;
revoke execute on function public._next_serial() from authenticated;
grant execute on function public.ingest_whatsapp_message(text, text, text, text) to service_role;

-- ---------------------------------------------------------------------
-- 7) تخزين الصور والمرفقات (خاص - لا يُفتح إلا لمن يحق له رؤية الشكوى)
-- ---------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit)
values ('attachments', 'attachments', false, 10485760)
on conflict (id) do nothing;

drop policy if exists "complaint files read" on storage.objects;
create policy "complaint files read" on storage.objects for select to authenticated
  using (bucket_id = 'attachments' and public.can_see_complaint(public.path_complaint_id(name)));

drop policy if exists "complaint files upload" on storage.objects;
create policy "complaint files upload" on storage.objects for insert to authenticated
  with check (bucket_id = 'attachments'
              and public.my_role() in ('admin', 'department')
              and public.can_see_complaint(public.path_complaint_id(name)));

-- ---------------------------------------------------------------------
-- 8) التحديث المباشر (Realtime)
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['complaints', 'assignments', 'notifications', 'notes', 'events'] loop
    begin
      execute format('alter publication supabase_realtime add table public.%I', t);
    exception when duplicate_object then null;
    end;
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- 9) فحص التأخير كل ساعة تلقائياً (pg_cron)
-- ---------------------------------------------------------------------
do $$
begin
  create extension if not exists pg_cron;
  perform cron.schedule('complaints-overdue-check', '5 * * * *', 'select public.check_overdue()');
exception when others then
  raise notice 'لم يتم تفعيل pg_cron (%). سيعمل فحص التأخير عند فتح لوحة التحكم.', sqlerrm;
end $$;

-- انتهى. الآن شغّل الملف 02_demo_data.sql لإضافة المستخدمين والبيانات التجريبية.
