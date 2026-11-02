-- =====================================================================
--  طلبيّة: مساعد واتساب. قاعدة البيانات
--  شغّلو مرة وحدة: Supabase > SQL Editor > New query > Run
--  بيشتغل جنب جداول نصيب والشكاوى وما بيلمسها.
-- =====================================================================

-- 1) الإيميلات المسموح إلها تفوت على صندوق الطلبيات
create table if not exists public.talabiye_members (
  email text primary key
);

-- 2) إعدادات المحل (سطر واحد)
create table if not exists public.talabiye_settings (
  id          int primary key default 1 check (id = 1),
  shop_name   text not null default '',
  auto_reply  boolean not null default false,   -- false: الرد بيستنى موافقتك. true: بينبعت لحالو
  catalog     text not null default '',         -- اختياري: أصناف وأسعار، سطر لكل صنف
  updated_at  timestamptz not null default now()
);
insert into public.talabiye_settings (id) values (1) on conflict do nothing;

-- 3) كل رسالة داخلة وطالعة
create table if not exists public.wa_messages (
  id          bigint generated always as identity primary key,
  wa_id       text unique,                      -- رقم الرسالة عند واتساب (منمنع التكرار)
  phone       text not null,
  name        text not null default '',
  direction   text not null check (direction in ('in', 'out')),
  type        text not null default 'text',     -- text, audio, location, image, ...
  body        text not null default '',
  order_id    uuid,
  created_at  timestamptz not null default now()
);
create index if not exists wa_messages_phone on public.wa_messages (phone, created_at desc);

-- 4) الطلبيات: وحدة مفتوحة لكل زبون لحد ما تتأكد أو تنلغى
create table if not exists public.wa_orders (
  id            uuid primary key default gen_random_uuid(),
  phone         text not null,
  name          text not null default '',
  status        text not null default 'draft' check (status in ('draft', 'confirmed', 'cancelled')),
  data          jsonb not null default '{}'::jsonb,   -- القطع، العنوان، المجموع، الناقص...
  reply         text not null default '',             -- الرد المقترح
  reply_status  text not null default 'none' check (reply_status in ('none', 'pending', 'sent', 'failed')),
  reply_error   text not null default '',
  last_in_at    timestamptz not null default now(),   -- آخر رسالة من الزبون (نافذة الـ ٢٤ ساعة)
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists wa_orders_open on public.wa_orders (phone, status, updated_at desc);

create or replace function public.talabiye_touch() returns trigger
language plpgsql as $$
begin new.updated_at := now(); return new; end $$;
drop trigger if exists wa_orders_touch on public.wa_orders;
create trigger wa_orders_touch before update on public.wa_orders
  for each row execute function public.talabiye_touch();

create or replace function public.talabiye_is_member() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.talabiye_members
    where email = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- 5) الحماية: الأعضاء بس. الخدمة (service role) بتكتب من الواتساب.
alter table public.talabiye_members  enable row level security;
alter table public.talabiye_settings enable row level security;
alter table public.wa_messages       enable row level security;
alter table public.wa_orders         enable row level security;

drop policy if exists talabiye_members_self on public.talabiye_members;
create policy talabiye_members_self on public.talabiye_members
  for select to authenticated using (email = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists talabiye_settings_members on public.talabiye_settings;
create policy talabiye_settings_members on public.talabiye_settings
  for all to authenticated using (public.talabiye_is_member()) with check (public.talabiye_is_member());

drop policy if exists wa_messages_members on public.wa_messages;
create policy wa_messages_members on public.wa_messages
  for select to authenticated using (public.talabiye_is_member());

drop policy if exists wa_orders_members on public.wa_orders;
create policy wa_orders_members on public.wa_orders
  for all to authenticated using (public.talabiye_is_member()) with check (public.talabiye_is_member());

revoke all on public.talabiye_members, public.talabiye_settings, public.wa_messages, public.wa_orders from anon;

-- 6) التحديث الفوري: الطلبية بتطلع عالشاشة أول ما توصل الرسالة
do $$ begin alter publication supabase_realtime add table public.wa_orders;
exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.wa_messages;
exception when duplicate_object then null; end $$;

-- 7) حطي إيميلك هون (نفس الإيميل اللي بتعمليه بـ Authentication > Users)
insert into public.talabiye_members (email) values
  (lower('my-email@example.com'))
on conflict do nothing;
