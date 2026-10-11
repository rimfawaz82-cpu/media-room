-- =====================================================================
--  دفتر مزاد نصيب — قاعدة البيانات المشتركة
--  شغّله مرة وحدة من Supabase: SQL Editor > New query > Run
--  (بيشتغل جنب جداول تطبيق الشكاوى وما بيلمسها)
-- =====================================================================

-- 1) الإيميلات المسموح لها تفوت عالدفتر
create table if not exists public.naseeb_members (
  email text primary key
);

-- 2) كل سجلات الدفتر: coll = نوع السجل (cartons, items, sales, ...)
create table if not exists public.naseeb_kv (
  coll       text not null,
  id         text not null,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  updated_by text,
  primary key (coll, id)
);

create or replace function public.naseeb_touch() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  new.updated_by := auth.jwt() ->> 'email';
  return new;
end $$;

drop trigger if exists naseeb_kv_touch on public.naseeb_kv;
create trigger naseeb_kv_touch before insert or update on public.naseeb_kv
  for each row execute function public.naseeb_touch();

create or replace function public.naseeb_is_member() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.naseeb_members
    where email = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- 3) الحماية: بس الأعضاء بيقروا وبيكتبوا
alter table public.naseeb_members enable row level security;
alter table public.naseeb_kv      enable row level security;

drop policy if exists naseeb_members_self on public.naseeb_members;
create policy naseeb_members_self on public.naseeb_members
  for select to authenticated
  using (email = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists naseeb_kv_members on public.naseeb_kv;
create policy naseeb_kv_members on public.naseeb_kv
  for all to authenticated
  using (public.naseeb_is_member())
  with check (public.naseeb_is_member());

revoke all on public.naseeb_members, public.naseeb_kv from anon;

-- 4) التحديث الفوري بين الأجهزة
do $$
begin
  alter publication supabase_realtime add table public.naseeb_kv;
exception when duplicate_object then null;
end $$;

-- 5) حط إيميلك وإيميل شريكك هون (نفس الإيميلات يلي بتعملهم بـ Authentication > Users)
insert into public.naseeb_members (email) values
  (lower('my-email@example.com')),
  (lower('partner-email@example.com'))
on conflict do nothing;

-- =====================================================================
--  صور القطع (Supabase Storage)
--  الصور بتنقرا برابط مباشر (أسماءها عشوائية 32 حرف)، بس الأعضاء بيرفعوا وبيمحوا
-- =====================================================================
insert into storage.buckets (id, name, public) values ('naseeb', 'naseeb', true)
on conflict (id) do nothing;

drop policy if exists naseeb_photos_insert on storage.objects;
create policy naseeb_photos_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'naseeb' and public.naseeb_is_member());

drop policy if exists naseeb_photos_update on storage.objects;
create policy naseeb_photos_update on storage.objects
  for update to authenticated
  using (bucket_id = 'naseeb' and public.naseeb_is_member());

drop policy if exists naseeb_photos_delete on storage.objects;
create policy naseeb_photos_delete on storage.objects
  for delete to authenticated
  using (bucket_id = 'naseeb' and public.naseeb_is_member());
