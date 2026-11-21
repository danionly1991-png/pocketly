-- Spec 03: categories + expenses, RLS, updated_at trigger, default-category seeding, RPCs.

-- ---------------------------------------------------------------------------
-- 1. Shared updated_at trigger function
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- 2. categories
-- ---------------------------------------------------------------------------
create table public.categories (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name        text not null,
  icon_type   text not null,
  icon_value  text not null,
  is_default  boolean not null default false,
  is_fallback boolean not null default false,   -- true only for the seeded "Other" (deviation D1)
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint categories_name_check
    check (name = btrim(name) and char_length(name) between 1 and 30),
  constraint categories_icon_type_check
    check (icon_type in ('emoji', 'image')),
  constraint categories_icon_value_check
    check (
      (icon_type = 'emoji' and char_length(icon_value) between 1 and 16)
      or (icon_type = 'image'
          and icon_value ~ '^[0-9a-f-]{36}/[0-9a-f]{32}\.webp$'
          and split_part(icon_value, '/', 1) = user_id::text)
    ),
  constraint categories_fallback_is_default_check
    check (not is_fallback or is_default)
);

comment on column public.categories.is_fallback is
  'The undeletable "Other" category. Expenses of deleted categories move here. One per user.';

create unique index categories_user_lower_name_key on public.categories (user_id, lower(name));
create unique index categories_one_fallback_per_user on public.categories (user_id) where is_fallback;
create index categories_user_id_idx on public.categories (user_id);

create trigger categories_set_updated_at
  before update on public.categories
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 3. expenses
-- ---------------------------------------------------------------------------
create table public.expenses (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  -- NO ACTION rather than RESTRICT (deviation D2): it still blocks deleting a category
  -- that has expenses, but lets an auth.users delete cascade through both tables.
  category_id uuid not null references public.categories (id),
  amount      numeric(12, 2) not null,
  spent_on    date not null,                     -- the day, in Asia/Karachi time
  note        text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint expenses_amount_check check (amount > 0 and amount <= 9999999.99),
  constraint expenses_note_check check (note is null or char_length(note) <= 500)
);

create index expenses_user_spent_idx on public.expenses (user_id, spent_on desc, created_at desc);
create index expenses_category_id_idx on public.expenses (category_id);  -- FK index (advisor)

create trigger expenses_set_updated_at
  before update on public.expenses
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. Row Level Security
-- ---------------------------------------------------------------------------
alter table public.categories enable row level security;
alter table public.expenses   enable row level security;

create policy categories_select_own on public.categories
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy categories_insert_own on public.categories
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy categories_update_own on public.categories
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy categories_delete_own on public.categories
  for delete to authenticated
  using ((select auth.uid()) = user_id and not is_fallback);

create policy expenses_select_own on public.expenses
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy expenses_insert_own on public.expenses
  for insert to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.categories c
      where c.id = category_id and c.user_id = (select auth.uid())
    )
  );

create policy expenses_update_own on public.expenses
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.categories c
      where c.id = category_id and c.user_id = (select auth.uid())
    )
  );

create policy expenses_delete_own on public.expenses
  for delete to authenticated
  using ((select auth.uid()) = user_id);

-- ---------------------------------------------------------------------------
-- 5. Table privileges (deviation D3)
--    The user's JWT can be read out of the (signed, not encrypted) Flask cookie, so a
--    user could call PostgREST directly. Column grants stop them setting is_default,
--    is_fallback, user_id or timestamps themselves.
-- ---------------------------------------------------------------------------
revoke all on public.categories, public.expenses from anon;
revoke all on public.categories, public.expenses from authenticated;
grant select, delete on public.categories, public.expenses to authenticated;
grant insert (name, icon_type, icon_value) on public.categories to authenticated;
grant update (name, icon_type, icon_value) on public.categories to authenticated;
grant insert (category_id, amount, spent_on, note) on public.expenses to authenticated;
grant update (category_id, amount, spent_on, note) on public.expenses to authenticated;

-- ---------------------------------------------------------------------------
-- 6. Default categories: private seeding function, auth.users trigger, backfill
--    Lives in a non-exposed "private" schema so it can't be called through the API.
-- ---------------------------------------------------------------------------
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create or replace function private.seed_default_categories(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_signed_up timestamptz;
begin
  select u.created_at into v_signed_up from auth.users u where u.id = p_user_id;

  -- created_at = signup time, so the dashboard's month list can start at the signup month (D6).
  insert into public.categories (user_id, name, icon_type, icon_value, is_default, is_fallback, created_at)
  select p_user_id, d.name, 'emoji', d.icon, true, d.name = 'Other', coalesce(v_signed_up, now())
  from (values
    ('Food', '🍔'),
    ('Transport', '🚌'),
    ('Mobile top-up', '📱'),
    ('Shopping', '🛍️'),
    ('Education', '📚'),
    ('Entertainment', '🎬'),
    ('Other', '📦')
  ) as d(name, icon)
  where not exists (
    select 1 from public.categories c
    where c.user_id = p_user_id and lower(c.name) = lower(d.name)
  )
  on conflict do nothing;   -- idempotent: also skips a second fallback if "Other" was renamed
end;
$$;

create or replace function private.handle_new_user_categories()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.seed_default_categories(new.id);
  return new;
end;
$$;

revoke all on function private.seed_default_categories(uuid) from public, anon, authenticated;
revoke all on function private.handle_new_user_categories() from public, anon, authenticated;
grant usage on schema private to supabase_auth_admin;
grant execute on function private.handle_new_user_categories() to supabase_auth_admin;

create trigger on_auth_user_created_seed_categories
  after insert on auth.users
  for each row execute function private.handle_new_user_categories();

-- Backfill users who signed up before this migration (idempotent).
select private.seed_default_categories(u.id) from auth.users u;

-- ---------------------------------------------------------------------------
-- 7. RPC functions (security invoker, so RLS applies as the calling user)
-- ---------------------------------------------------------------------------

-- One round trip for the dashboard's numbers.
--   first_month          : first month the Month selector offers (earliest expense or signup)
--   month_to_date_total  : current month, day 1 .. p_today (the "Spent this month" tab)
--   view_total           : total for the viewed range (a past month, or one selected day)
create or replace function public.dashboard_totals(p_today date, p_view_from date, p_view_to date)
returns table (first_month date, month_to_date_total numeric, view_total numeric)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    date_trunc('month', least(
      (select min(e.spent_on) from public.expenses e where e.user_id = (select auth.uid())),
      (select (min(c.created_at) at time zone 'Asia/Karachi')::date
         from public.categories c where c.user_id = (select auth.uid())),
      p_today
    ))::date,
    coalesce((select sum(e.amount) from public.expenses e
              where e.user_id = (select auth.uid())
                and e.spent_on between date_trunc('month', p_today)::date and p_today), 0),
    coalesce((select sum(e.amount) from public.expenses e
              where e.user_id = (select auth.uid())
                and e.spent_on between p_view_from and p_view_to), 0);
$$;

-- Expense count per category, for the categories page ("{n} expenses will move to Other.").
create or replace function public.category_expense_counts()
returns table (category_id uuid, expense_count bigint)
language sql
stable
security invoker
set search_path = ''
as $$
  select e.category_id, count(*)
  from public.expenses e
  where e.user_id = (select auth.uid())
  group by e.category_id;
$$;

-- Atomically move a category's expenses to the user's fallback ("Other"), then delete it.
-- Returns how many expenses were moved. Error messages are matched by the Flask service.
create or replace function public.delete_category(p_category_id uuid)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_uid       uuid := (select auth.uid());
  v_target    public.categories%rowtype;
  v_fallback  uuid;
  v_moved     integer;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;

  select * into v_target
  from public.categories
  where id = p_category_id and user_id = v_uid
  for update;

  if not found then
    raise exception 'category_not_found' using errcode = 'P0002';
  end if;
  if v_target.is_fallback then
    raise exception 'cannot_delete_fallback' using errcode = 'P0001';
  end if;

  select id into v_fallback from public.categories where user_id = v_uid and is_fallback;
  if v_fallback is null then
    raise exception 'fallback_missing' using errcode = 'P0001';
  end if;

  update public.expenses
     set category_id = v_fallback
   where user_id = v_uid and category_id = p_category_id;
  get diagnostics v_moved = row_count;

  delete from public.categories where id = p_category_id and user_id = v_uid;
  return v_moved;
end;
$$;

revoke all on function public.set_updated_at() from public, anon, authenticated;
revoke all on function public.dashboard_totals(date, date, date) from public, anon;
revoke all on function public.category_expense_counts() from public, anon;
revoke all on function public.delete_category(uuid) from public, anon;
grant execute on function public.dashboard_totals(date, date, date) to authenticated;
grant execute on function public.category_expense_counts() to authenticated;
grant execute on function public.delete_category(uuid) to authenticated;
