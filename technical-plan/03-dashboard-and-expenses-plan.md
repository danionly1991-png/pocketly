# Spec 03 — Dashboard, Expenses & Categories: Technical Implementation Plan

> This plan is written for an implementer (Sonnet) with **no access to the planning conversation**. Follow it literally. Where it says "verify", actually run the check.

---

## 0. Context

Specs 01–02 shipped the Flask app, the design system, and Supabase email/password auth (cookie-only sessions, a fresh Supabase client per request, `@login_required`). `/dashboard` is still a "Hi, {name}" placeholder in `app/routes/auth.py`, and `/analytics` is a public coming-soon page. Spec 03 (`specs/03-dashboard-and-expenses-spec.md`, **read it fully first**) replaces the placeholder with the real app. Users get a monthly expense list with month/day filters, a running "Spent this month" total, an add-expense dialog, expense detail/edit/delete, and per-user categories with emoji or uploaded-photo icons.

**Facts checked during planning (as of 2026-11-22):**
- The Supabase project (Postgres 17.12) has **no tables in `public`, no migrations, no storage buckets, and no triggers on `auth.users`**. It has **3 existing users** (they need the default categories backfilled).
- `supabase==2.34.1` / `postgrest==2.34.1` / `storage3==2.34.1` are installed. Their APIs were read from the installed source (see §3).
- `zoneinfo.ZoneInfo("Asia/Karachi")` **fails on this Windows machine** (`ZoneInfoNotFoundError`), because Windows has no IANA tz database, so **`tzdata` must be added**.
- `Pillow==13.0.0` has `cp314` wheels for manylinux_2_28 (Vercel runs Amazon Linux 2023, glibc 2.34, so it's fine) and for Windows.
- `vercel.json` still excludes `technical plan/**` (old folder name, with a space). The folder is now `technical-plan/`, and `supabase/` must be excluded too.
- PostgREST aggregate functions (`select=amount.sum()`) are **disabled by default on Supabase**, so totals use a SQL function called over RPC (still a database `sum()`, as the spec requires).

**Decisions confirmed with Daniyal:**
- Add an `is_fallback boolean` column to `categories` to identify "Other" even after it's renamed (deviation D1).
- **There is no limit on the number of custom categories.** Nothing in the DB, services, forms or UI may cap it. The category chip grid in the add form scrolls instead.

---

## 1. Summary

**Delivers**
- Two Supabase migrations: the `categories` + `expenses` tables, RLS, the `updated_at` trigger, default-category seeding (trigger + backfill), RPC functions (dashboard totals, category usage counts, atomic delete-and-reassign), and the `category-icons` public bucket with per-user-folder storage policies.
- `/dashboard`: the month selector, day picker, Analytics button, "Spent this month" tab, profile menu, numbered expense list, empty states and the floating "+" button opening a `<dialog>` add panel.
- `/expenses/<id>` detail, `/expenses/<id>/edit`, and `POST /expenses/<id>/delete` with a confirm dialog.
- `/categories`: list, add, edit (rename + emoji/photo icon) and delete-with-reassign-to-Other, with photo upload resized to 128×128 WEBP via Pillow.
- `/analytics` becomes login-required and links back to the dashboard.
- Jinja filters for `money` and the date formats, with all "today" logic in Asia/Karachi.

**Out of scope:** analytics/charts, budgets/limits/alerts, search/sort/export, recurring expenses, other currencies, profile/settings pages, pagination, an automated test suite committed to the repo.

---

## 2. Supabase changes (applied by Claude Code through the Supabase MCP)

### 2.1 Order

1. Write `supabase/migrations/20261122_01_categories_expenses.sql` (§2.2) and apply it with `mcp__supabase__apply_migration` (name `20261122_01_categories_expenses`, query = the file contents, **byte-identical**).
2. Write `supabase/migrations/20261122_02_category_icons_storage.sql` (§2.3) and apply it with name `20261122_02_category_icons_storage`.
3. Run the verification queries (§2.4), the RLS impersonation tests (§2.5), and `mcp__supabase__get_advisors` for both `security` and `performance` (§2.6).
4. Commit both files: `feat(db): categories, expenses, RLS, seeding, icon storage`.

**Destructive operations: none.** Everything is a `create`, and no existing table is dropped, truncated or altered. One **sensitive** change: an `after insert` trigger on `auth.users`. It's required by spec §5.4 and doesn't change auth *settings*. The rollback SQL (§2.7) is destructive and must **only** be run with Daniyal's explicit approval.

If a migration fails partway, `apply_migration` runs it in a transaction, so nothing is applied. Fix the SQL and re-apply. Never hand-edit the live DB outside a migration.

### 2.2 `supabase/migrations/20261122_01_categories_expenses.sql`

```sql
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
```

Notes for the implementer:
- `on conflict do nothing` with no target covers both unique indexes. Don't add a conflict target.
- The `icon_value` image regex matches the path Flask generates: `{user_uuid}/{uuid4().hex}.webp` (32 hex characters, no dashes). **Use `uuid4().hex`** in `storage.py`, or the check fails.
- **No row limit on categories anywhere.** Don't add a count check, trigger or policy.

### 2.3 `supabase/migrations/20261122_02_category_icons_storage.sql`

```sql
-- Spec 03: public bucket for category icons + per-user-folder write policies.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('category-icons', 'category-icons', true, 524288, array['image/webp'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- Public URLs are served without RLS (public bucket). This SELECT policy is still
-- needed because Storage only deletes objects the caller can see (deviation D5).
create policy category_icons_select_own on storage.objects
  for select to authenticated
  using (bucket_id = 'category-icons'
         and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy category_icons_insert_own on storage.objects
  for insert to authenticated
  with check (bucket_id = 'category-icons'
              and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy category_icons_update_own on storage.objects
  for update to authenticated
  using (bucket_id = 'category-icons'
         and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'category-icons'
              and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy category_icons_delete_own on storage.objects
  for delete to authenticated
  using (bucket_id = 'category-icons'
         and (storage.foldername(name))[1] = (select auth.uid())::text);
```

The bucket only accepts `image/webp` up to 512 KB, a second line of defence after Flask's checks. Flask **must** upload with `content-type: image/webp`, or Storage rejects the default `text/plain`.

### 2.4 Verification queries (run with `mcp__supabase__execute_sql`, then compare)

```sql
-- a) Tables, columns, RLS flag
select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name in ('categories','expenses')
order by table_name, ordinal_position;
select relname, relrowsecurity from pg_class
where relnamespace = 'public'::regnamespace and relname in ('categories','expenses');   -- both true

-- b) Constraints and indexes
select conrelid::regclass, conname, pg_get_constraintdef(oid) from pg_constraint
where conrelid in ('public.categories'::regclass, 'public.expenses'::regclass);
select tablename, indexname, indexdef from pg_indexes
where schemaname = 'public' and tablename in ('categories','expenses');

-- c) Policies (8 on public tables, 4 on storage.objects for this bucket)
select schemaname, tablename, policyname, cmd, qual, with_check from pg_policies
where (schemaname = 'public' and tablename in ('categories','expenses'))
   or (schemaname = 'storage' and policyname like 'category_icons_%');

-- d) Triggers and functions
select tgname, tgrelid::regclass from pg_trigger
where not tgisinternal and tgname in ('categories_set_updated_at','expenses_set_updated_at','on_auth_user_created_seed_categories');
select n.nspname, p.proname, p.prosecdef from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname in ('public','private');

-- e) Seeding: every user has 7 defaults and exactly one fallback
select u.id,
       count(c.*) filter (where c.is_default) as defaults,
       count(c.*) filter (where c.is_fallback) as fallbacks
from auth.users u left join public.categories c on c.user_id = u.id
group by u.id;                                 -- expect 3 rows, each 7 / 1

-- f) Bucket
select id, public, file_size_limit, allowed_mime_types from storage.buckets where id = 'category-icons';

-- g) Privileges: anon has none, authenticated only the column grants
select grantee, table_name, privilege_type from information_schema.role_table_grants
where table_schema = 'public' and table_name in ('categories','expenses') and grantee in ('anon','authenticated');
```

### 2.5 RLS impersonation tests (SQL, always rolled back, not destructive)

Pick two real user ids from `auth.users` (A and B) and B's "Food" category id. Run this **as one `execute_sql` call** wrapped in `begin … rollback`:

```sql
begin;
set local role authenticated;
select set_config('request.jwt.claims', json_build_object('sub','<A>','role','authenticated')::text, true);

select count(*) as b_categories_visible from public.categories where user_id = '<B>';      -- 0
select count(*) as b_expenses_visible   from public.expenses   where user_id = '<B>';      -- 0
update public.categories set name = 'hacked' where user_id = '<B>' returning id;           -- 0 rows
delete from public.categories where user_id = '<B>' returning id;                          -- 0 rows
select public.dashboard_totals(current_date, current_date, current_date);                  -- works, A's numbers only
rollback;
```

Then each of these **separately** (each one should raise an error; each is its own `begin … rollback`):
- `insert into public.expenses (category_id, amount, spent_on) values ('<B_food_id>', 10, current_date);` → `new row violates row-level security policy` (42501).
- `update public.categories set is_fallback = false where user_id = '<A>';` → `permission denied for table categories` (column grant).
- `delete from public.categories where user_id = '<A>' and is_fallback returning id;` → 0 rows (policy).
- `select public.delete_category((select id from public.categories where user_id='<A>' and is_fallback));` → `cannot_delete_fallback`.
- Storage: `insert into storage.objects (bucket_id, name) values ('category-icons', '<B>/x.webp');` as A → RLS violation. Then the same with `'<A>/x.webp'` → succeeds (then rollback).

Also test the signup trigger end to end in Phase 1: Daniyal signs up a second test account through the app (needed anyway for the two-account test). Query (e) should then show it with 7 / 1.

### 2.6 Advisors

Run `mcp__supabase__get_advisors` with `type: "security"` and `type: "performance"`. Expected: no `rls_disabled_in_public`, no `function_search_path_mutable`, no `unindexed_foreign_keys`, and no `auth_rls_initplan` (we use `(select auth.uid())`). Fix anything new by **adding a follow-up migration file** (`20261122_03_...sql`), never by editing an applied one. Pre-existing project warnings (e.g. leaked-password protection) are auth settings: report them to Daniyal, don't change them.

### 2.7 Rollback (DESTRUCTIVE — only with Daniyal's explicit approval)

```sql
drop trigger if exists on_auth_user_created_seed_categories on auth.users;
drop policy if exists category_icons_select_own on storage.objects;  -- …and the other 3 category_icons_* policies
-- Storage objects must be deleted through the Storage API, not SQL.
drop table if exists public.expenses;
drop table if exists public.categories;
drop function if exists public.delete_category(uuid), public.category_expense_counts(),
  public.dashboard_totals(date, date, date), public.set_updated_at();
drop schema if exists private cascade;
```

---

## 3. supabase-py API (checked in the installed 2.34.1 source)

**Per-request user client.** `Client.__init__` merges `options.headers` and keeps a supplied `Authorization` header, and `Client.create` skips `get_session()` when one is given. PostgREST and Storage clients are built lazily from `self.options.headers`. So:

```python
from supabase import ClientOptions, create_client
create_client(url, anon_key, options=ClientOptions(
    headers={"Authorization": f"Bearer {access_token}"},
    flow_type="implicit", persist_session=False, auto_refresh_token=False,
))
```

Every `.table()`, `.rpc()` and `.storage` call on it then runs as the user, and RLS applies. Keep this as a **separate** client from the anon one in `get_supabase()` (that one is used for auth/refresh in `before_request`).

| Operation | Exact call | Notes |
|---|---|---|
| List | `c.table("expenses").select(COLS).gte("spent_on", a).lte("spent_on", b).order("spent_on", desc=True).order("created_at", desc=True).execute().data` | `order()` calls append. Returns a list of dicts. PostgREST caps at 1000 rows (fine for a month). |
| Embed category | `COLS = "id,amount::text,spent_on,note,created_at,category:categories(id,name,icon_type,icon_value,is_default,is_fallback)"` | `amount::text` makes PostgREST send the numeric as a string, so it maps to an exact `Decimal`, never a float. The key stays `amount`. |
| Single row | `c.table(...).select(COLS).eq("id", id).maybe_single().execute()` | Returns **`None`** when there are 0 rows (not visible = not found → 404). |
| Insert | `c.table("expenses").insert({...}).execute().data[0]` | Returns the row (representation by default). Send `amount` as `str(Decimal)` and dates as ISO strings. **Don't send `user_id`** (column grant; the default is `auth.uid()`). |
| Update | `c.table("expenses").update({...}).eq("id", id).execute().data` | An empty list means not found or not owned. |
| Delete | `c.table("expenses").delete().eq("id", id).execute().data` | An empty list means not found. |
| RPC | `c.rpc("dashboard_totals", {"p_today": "2026-11-22", "p_view_from": ..., "p_view_to": ...}).execute().data` | Table-returning → a list with one dict. Numerics come back as JSON numbers, so convert with `Decimal(str(v))`. |
| RPC delete | `c.rpc("delete_category", {"p_category_id": id}).execute().data` | Scalar integer. Errors raise `postgrest.exceptions.APIError` with `.code` (e.g. `P0001`) and `.message` (`cannot_delete_fallback` …). |
| Upload | `c.storage.from_("category-icons").upload(path, data_bytes, {"content-type": "image/webp", "cache-control": "31536000", "upsert": "false"})` | Pass `bytes`. Returns `UploadResponse(path, full_path)`. Errors raise `storage3.exceptions.StorageApiError` (a subclass of `storage3.utils.StorageException`). |
| Public URL | `c.storage.from_("category-icons").get_public_url(path)` | Pure string building, no network call: `…/storage/v1/object/public/category-icons/{path}`. |
| Remove | `c.storage.from_("category-icons").remove([path])` | Returns the list of deleted objects. **An empty list means nothing was deleted** (not visible / not found), so log a warning. |

Error classes to catch in the data services: `postgrest.exceptions.APIError`, `storage3.utils.StorageException`, `httpx.HTTPError`, `OSError`. Useful PostgreSQL codes: `23505` unique violation, `42501` RLS/privilege, `23503` FK, `23514` check, `P0001`/`P0002` raised by `delete_category`.

---

## 4. Files, in implementation order

### Phase A — dependencies, config, plumbing

1. **`requirements.txt`**: add `Pillow==13.0.0` and `tzdata==2026.6`. tzdata is needed because Windows has no IANA tz database (verified: `Asia/Karachi` lookup fails locally), and it also guarantees the zone exists on Vercel. Run `pip install -r requirements.txt` and check `python -c "import PIL, zoneinfo; zoneinfo.ZoneInfo('Asia/Karachi')"`.

2. **`app/config.py`**: add `MAX_CONTENT_LENGTH = 3 * 1024 * 1024`. Flask rejects bigger bodies with 413, a cap above the 2 MB icon rule and below Vercel's 4.5 MB.

3. **`app/supabase_client.py`**: add, next to `get_supabase()`:
   ```python
   def get_user_supabase(access_token: str | None):
       """Client that sends the logged-in user's JWT, so RLS applies as that user. None if unconfigured or no token."""
   ```
   Cache it on `g._supabase_user` and build it as in §3. Lazy-import `supabase` as the existing function does, and log a warning if it's unconfigured. Update the module docstring (two clients: anon for auth, user for data). **Don't import `auth_utils` here** (import cycle); the caller passes the token.

4. **`app/utils/__init__.py`** (empty) and **`app/utils/dates.py`**: time and formatting.
   ```python
   KARACHI = ZoneInfo("Asia/Karachi")
   def karachi_today() -> date                      # datetime.now(KARACHI).date(); never date.today()
   def month_start(d: date) -> date                 # d.replace(day=1)
   def month_end(first: date) -> date               # calendar.monthrange
   def shift_month(first: date, months: int) -> date
   def parse_month_param(value: str | None, current_month: date) -> date | None
       # regex ^\d{4}-(0[1-9]|1[0-2])$ ; 2000-01 <= month <= current_month ; else None
   def parse_day_param(value: str | None, month: date, today: date) -> date | None
       # regex ^\d{4}-\d{2}-\d{2}$ ; date.fromisoformat in try ; same year+month as `month` ; <= today ; else None
   def parse_iso_date(value: str | None) -> date | None   # used by the form; None on bad input
   def month_options(first_month: date, current_month: date) -> list[tuple[str, str]]
       # newest first: [("2026-11", "November 2026"), ("2026-10", "October 2026"), ...]
   def to_decimal(value) -> Decimal                 # Decimal(str(value)); None -> Decimal("0")
   # Jinja filters (accept date/Decimal; never float):
   def money(value) -> str          # Rs 1,250 | Rs 99.50 -> q = d.quantize(Decimal("0.01")); whole -> f"Rs {int(q):,}" else f"Rs {q:,.2f}"
   def short_date(d) -> str         # "Sat, 21 Nov"     -> f"{d:%a}, {d.day} {d:%b}"  (no %-d: breaks on Windows)
   def long_date(d) -> str          # "Saturday, 21 November 2026"
   def month_label(d) -> str        # "November 2026"
   def month_name(d) -> str         # "November"
   def day_month(d) -> str          # "22 Nov"
   def day_name(d) -> str           # "Saturday"
   def amount_input(d: Decimal) -> str   # value for <input>: "1250" or "99.50"
   def register_filters(app: Flask) -> None   # registers all of the above filters by name
   ```

5. **`app/__init__.py`**:
   - Call `register_filters(app)`.
   - Register `expenses_bp` and `categories_bp`.
   - `inject_globals`: `current_year = karachi_today().year`; `get_started_url` → `expenses.dashboard`; add `app_shell = request.blueprint in {"expenses", "categories", "placeholders"}` (navbar shows the logo only on app pages).
   - CSRF handler `post_only` map, adding POST-only endpoints so a failed token never redirects to a GET-less URL (405): `"expenses.create_expense": "expenses.dashboard"`, `"expenses.delete_expense": "expenses.dashboard"`, `"categories.update": "categories.index"`, `"categories.delete": "categories.index"`.
   - `@app.errorhandler(413)`: flash `"Upload a JPG, PNG or WEBP image under 2 MB."` (error) and redirect to `categories.index`.

6. **`app/auth_utils.py`**: `logged_out_only` → `url_for("expenses.dashboard")`. Add `@property initial` on `CurrentUser` → `(self.name or self.email or "?")[:1].upper()` (logic stays in Python).

### Phase B — services

7. **`app/services/db.py`** (new): shared data-layer plumbing.
   ```python
   UNAVAILABLE_MESSAGE = "Pocketly can't reach its database right now. Please try again in a moment."
   GENERIC_MESSAGE = "Something went wrong. Please try again."
   class DataError(Exception):                  # user_message, code, field (like AuthError)
   def user_client():                           # get_user_supabase(auth_utils.access_token()) or raise DataError(UNAVAILABLE_MESSAGE, "unavailable")
   CAUGHT = (APIError, StorageException, httpx.HTTPError, OSError)
   def friendly(error: Exception) -> DataError  # logs type + code only (never row data); maps codes:
       # 23505 -> code "duplicate"; 42501/23503 -> "forbidden"; others -> GENERIC_MESSAGE
   ```

8. **`app/services/storage.py`** (new):
   ```python
   BUCKET = "category-icons"; MAX_UPLOAD_BYTES = 2 * 1024 * 1024; ICON_SIZE = 128
   ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}; MAX_PIXELS = 40_000_000
   ICON_MESSAGE = "Upload a JPG, PNG or WEBP image under 2 MB."
   class IconError(ValueError)
   def process_icon(file: FileStorage) -> bytes
   def upload_icon(user_id: str, data: bytes) -> str          # returns path f"{user_id}/{uuid4().hex}.webp"
   def remove_icon(path: str | None) -> None                  # best effort: logs, never raises
   def icon_url(path: str) -> str                             # user_client().storage.from_(BUCKET).get_public_url(path)
   ```
   `process_icon` steps:
   - `data = file.stream.read(MAX_UPLOAD_BYTES + 1)`. If it's empty or longer than `MAX_UPLOAD_BYTES`, raise `IconError`.
   - `img = Image.open(BytesIO(data))`. If `img.format` isn't in `ALLOWED_FORMATS`, or `img.width * img.height > MAX_PIXELS`, raise.
   - `img.verify()`, then **re-open** (verify leaves the image unusable).
   - Then: `img = ImageOps.exif_transpose(img)` → `img.seek(0)` (first frame of an animated image) → convert to `"RGBA"` if it has alpha (`img.mode in ("RGBA","LA")` or `"transparency" in img.info`), else `"RGB"` → `ImageOps.fit(img, (128, 128), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))` → save to `BytesIO` as `format="WEBP", quality=85, method=4`.
   - Catch `(OSError, ValueError, Image.DecompressionBombError, SyntaxError)` → `IconError`.
   - Don't trust the file name or mimetype.

9. **`app/services/categories.py`** (new):
   ```python
   @dataclass(frozen=True)
   class Category: id: str; name: str; icon_type: str; icon_value: str; is_default: bool; is_fallback: bool; icon_url: str | None
   COLUMNS = "id,name,icon_type,icon_value,is_default,is_fallback"
   def to_category(row: dict) -> Category                    # icon_url only for image
   def list_categories() -> list[Category]                   # order is_fallback asc, created_at asc, name asc; NO limit
   def get_category(category_id: str) -> Category | None
   def expense_counts() -> dict[str, int]                    # rpc category_expense_counts
   def create_category(name: str, icon_type: str, icon_value: str) -> Category
   def update_category(category_id: str, name: str, icon_type: str, icon_value: str) -> Category | None
   def delete_category(category_id: str) -> int              # rpc; returns moved count
   ```
   - Duplicate (23505) → `DataError("You already have a category with this name.", code="duplicate", field="name")`.
   - `delete_category` maps the `APIError.message`: `category_not_found` → `DataError(code="not_found")`; `cannot_delete_fallback` → `DataError("This category can't be deleted.", code="fallback")`; anything else → generic.

10. **`app/services/expenses.py`** (new):
    ```python
    @dataclass(frozen=True)
    class Expense: id: str; amount: Decimal; spent_on: date; note: str | None; category: Category
    @dataclass(frozen=True)
    class Totals: first_month: date; month_to_date: Decimal; view_total: Decimal
    @dataclass(frozen=True)
    class DashboardView:
        today: date; current_month: date; month: date; day: date | None
        is_current_month: bool; month_options: list[tuple[str, str]]
        expenses: list[Expense]; totals: Totals
        date_min: date; date_max: date          # for the day picker (max = today in current month, else month end)
    def list_expenses(start: date, end: date) -> list[Expense]
    def get_expense(expense_id: str) -> Expense | None
    def create_expense(category_id: str, amount: Decimal, spent_on: date, note: str | None) -> dict   # returns {"id", "spent_on"}
    def update_expense(expense_id: str, category_id: str, amount: Decimal, spent_on: date, note: str | None) -> bool
    def delete_expense(expense_id: str) -> date | None   # spent_on of the deleted row, None if not found
    def dashboard_totals(today: date, view_from: date, view_to: date) -> Totals
    def build_dashboard(month_param: str | None, day_param: str | None) -> DashboardView
    ```
    `build_dashboard` logic:
    1. `today = karachi_today()` and `current = month_start(today)`. `month = parse_month_param(...) or current`, then `day = parse_day_param(day_param, month, today)`. Invalid params are **silently ignored**.
    2. The view range is `(day, day)` if there's a day, else `(month, month_end(month))`.
    3. Call `list_expenses(range)` and `dashboard_totals(today, range)`.
    4. `month_options(min(totals.first_month, month), current)`.

    - A 42501/23503 error on insert/update → `DataError("Please choose a category.", field="category_id")`.
    - `to_expense(row)` uses `Decimal(row["amount"])` and `date.fromisoformat(row["spent_on"])`.

### Phase C — forms

11. **`app/forms.py`**: add constants and two forms (keep the existing ones untouched).
    ```python
    AMOUNT_MESSAGE = "Enter an amount greater than 0."
    CATEGORY_MESSAGE = "Please choose a category."
    DATE_MESSAGE = "Please choose a valid date."           # missing/invalid (D8)
    FUTURE_DATE_MESSAGE = "Date can't be in the future."
    NOTE_MESSAGE = "Note can be up to 500 characters."
    CATEGORY_NAME_MESSAGE = "Category name must be 1–30 characters."   # (D8)
    DUPLICATE_NAME_MESSAGE = "You already have a category with this name."
    EMOJI_MESSAGE = "Please choose an emoji."
    MAX_AMOUNT = Decimal("9999999.99")
    PRESET_EMOJIS = ["🍔","🍕","☕","🍩","🛒","🚌","🚕","⛽","✈️","📱","💡","💧","🏠","🧾","💊",
                     "🏥","🎁","🎉","🛍️","👕","📚","✏️","🎓","🎬","🎮","🎵","⚽","💇","🐾","📦"]  # 30, includes all 7 defaults

    class ExpenseForm(FlaskForm):
        amount = StringField("Amount", filters=[_strip])
        category_id = StringField("Category", filters=[_strip])
        spent_on = StringField("Date", filters=[_strip])
        note = TextAreaField("Note", filters=[_strip, _none_if_empty], validators=[Optional(), Length(max=500, message=NOTE_MESSAGE)])
        return_month = HiddenField(); return_day = HiddenField()
        allowed_category_ids: set[str]   # set by the route before validate
        amount_value: Decimal | None; spent_on_value: date | None   # set by validators
        def validate_amount(self, field)       # strip commas; Decimal(); is_finite; 0 < x <= MAX; x.as_tuple().exponent >= -2; else AMOUNT_MESSAGE
        def validate_category_id(self, field)  # field.data in self.allowed_category_ids else CATEGORY_MESSAGE
        def validate_spent_on(self, field)     # parse_iso_date -> DATE_MESSAGE; > karachi_today() -> FUTURE_DATE_MESSAGE

    class CategoryForm(FlaskForm):
        name = StringField("Name", filters=[_strip], validators=[DataRequired(CATEGORY_NAME_MESSAGE), Length(min=1, max=30, message=CATEGORY_NAME_MESSAGE)])
        icon_type = RadioField("Icon", choices=[("emoji", "Emoji"), ("image", "Upload photo")], default="emoji")
        emoji = StringField("Emoji")                   # rendered as a radio grid by hand
        photo = FileField("Photo")                     # flask_wtf.file.FileField
        has_existing_image: bool = False               # set by the route when editing an image category
        icon_bytes: bytes | None = None                # set by validate_photo
        def validate_emoji(self, field)   # if icon_type == "emoji" and data not in PRESET_EMOJIS -> EMOJI_MESSAGE
        def validate_photo(self, field)   # if icon_type == "image": file given -> storage.process_icon -> icon_bytes (IconError -> ICON_MESSAGE);
                                          # no file and not has_existing_image -> ICON_MESSAGE
    ```
    `RadioField` keeps its built-in choice validation (only `emoji`/`image`).

### Phase D — routes

12. **`app/routes/expenses.py`** (new): `expenses_bp = Blueprint("expenses", __name__)`. Every view has `@login_required`. Helpers:
    - `_load_categories()` returns a list, or flashes the `DataError` and returns `[]`.
    - `_dashboard_params(month: date, day: date | None, today: date) -> dict` drops `month` when it's the current month.
    - `_redirect_after_save(view_month, view_day, spent_on)`: month = `month_start(spent_on)`; day = `view_day` if `view_day == spent_on` else None (D7).
13. **`app/routes/categories.py`** (new): `categories_bp = Blueprint("categories", __name__)`, with the views in §5.
14. **`app/routes/auth.py`**: delete the dashboard section and the `dashboard` view. Replace `url_for("auth.dashboard")` (3 places) with `url_for("expenses.dashboard")`. Update the docstring.
15. **`app/routes/placeholders.py`**:
    - `@login_required` on `analytics`.
    - `PAGES["analytics"] = ("Analytics", "Charts of where your money goes are coming soon.")`.
    - Pass `back_url=url_for("expenses.dashboard")` and `back_label="Back to dashboard"`.
16. **`app/routes/__init__.py`**: export `expenses_bp` and `categories_bp`.

### Phase E — styles, templates, JS (details in §6)

17. **`app/styles/input.css`** `@layer components` additions: `.expense-row`, `.category-chip`, `.emoji-chip`, `.icon-circle`, `.fab`, `.avatar`, `.dialog-panel`, `.dialog-confirm`, `.select-pill`, `.spent-tab`, `.badge`, `.note-box`. Exact classes are in §6.
18. **Templates**:
    - Components: `components/category_icon.html`, `components/expense_row.html`, `components/expense_form.html`, `components/confirm_dialog.html`, `components/top_bar.html`, `components/profile_menu.html`.
    - Pages: `dashboard.html` (rewrite), `expenses/detail.html`, `expenses/edit.html`, `categories/index.html`.
    - Edits: `components/navbar.html` and `coming_soon.html`.
19. **JS** (`public/static/js/`): `dialogs.js`, `dashboard.js`, `expense-form.js`, `category-form.js`. Each page loads only what it needs in `{% block scripts %}` with `defer`.

### Phase F — build, docs, deploy config

20. **`vercel.json`**: `"excludeFiles": "{.venv/**,specs/**,technical-plan/**,supabase/**,app/styles/**,public/**}"`. Also check `.vercelignore` and add `supabase/` and `technical-plan/` there if it lists folders.
21. **Rebuild `public/static/css/output.css`** with `--minify` and commit it.
22. **`README.md`**: a migrations section (the files, how Claude Code applies them through the Supabase MCP, and that Daniyal doesn't run SQL), the `category-icons` bucket (public read, owner-folder writes, WEBP 128×128), the new deps, and the updated file tree.
23. **`CLAUDE.md`**:
    - Roadmap: 03 "Dashboard, expenses & categories" Done; 04 "Analytics" Next; remove the old 04/05 rows.
    - Architecture: `utils/dates.py`, the new services, the user-token client `get_user_supabase()`, `supabase/migrations/`, and placeholders still serving only `/analytics` (now login-required).

---

## 5. Routes

All routes use `@login_required`. `<uuid:…>` converters 404 on malformed ids before any DB call.

| Endpoint | Route | Method | Params / form | Success | Failure |
|---|---|---|---|---|---|
| `expenses.dashboard` | `/dashboard` | GET | `month=YYYY-MM`, `day=YYYY-MM-DD`, `add=1` (opens the panel without JS) | render `dashboard.html` | Bad params are ignored (default view). A `DataError` flashes its message and renders with an empty list. |
| `expenses.create_expense` | `/expenses` | POST | ExpenseForm + `return_month`, `return_day` | flash **"Expense added."** → redirect per D7 | Validation or field `DataError`: re-render `dashboard.html` (view rebuilt from `return_month`/`return_day`) with `open_add=True` and the form's values and errors, status 200 |
| `expenses.detail` | `/expenses/<uuid:expense_id>` | GET | — | render `expenses/detail.html` | `None` → `abort(404)` |
| `expenses.edit` | `/expenses/<uuid:expense_id>/edit` | GET, POST | ExpenseForm (pre-filled on GET using `amount_input`) | flash **"Expense updated."** → `expenses.detail` | Re-render with errors. `update_expense` False → 404 |
| `expenses.delete_expense` | `/expenses/<uuid:expense_id>/delete` | POST | CSRF only | flash **"Expense deleted."** → dashboard of the deleted expense's month | Not found → 404 |
| `categories.index` | `/categories` | GET | `edit=<uuid>` (optional: the form switches to edit mode; unknown id is ignored) | render `categories/index.html` | `DataError` flash |
| `categories.create` | `/categories` | POST | CategoryForm (multipart) | flash **"Category added."** → `categories.index` | Re-render with errors |
| `categories.update` | `/categories/<uuid:category_id>` | POST | CategoryForm | flash **"Category updated."** → `categories.index` | Re-render (edit mode) with errors. Unknown id → 404 |
| `categories.delete` | `/categories/<uuid:category_id>/delete` | POST | CSRF only | flash **"Category deleted."**, or **"Category deleted. {n} expense(s) moved to {fallback name}."** → `categories.index` | Fallback → flash **"{name} can't be deleted."**; not found → 404 |
| `placeholders.analytics` | `/analytics` | GET | — | `coming_soon.html` + "← Back to dashboard" | — |

Category write logic (in the route, using the services):
- **Create:** emoji → `create_category(name, "emoji", emoji)`. Image → `path = upload_icon(user.id, form.icon_bytes)`, then `create_category(name, "image", path)`. If the create raises, `remove_icon(path)` and re-raise / show the error.
- **Update:** `old = get_category(id)` (None → 404). Work out the new icon:
  - emoji → `("emoji", emoji)`
  - image with new bytes → upload → `("image", new_path)`
  - image without bytes and `old.icon_type == "image"` → keep `old.icon_value`

  Then `update_category(...)`. On failure, remove `new_path`. On success, if `old.icon_type == "image"` and `old.icon_value` changed, `remove_icon(old.icon_value)`.
- **Delete:** `cat = get_category(id)` (None → 404). If `cat.is_fallback`, flash and redirect. Then `moved = delete_category(id)`; if it was an image, `remove_icon(cat.icon_value)`.
- The fallback name for messages comes from `list_categories()` (the category with `is_fallback`), so a renamed "Other" shows its new name.

---

## 6. Templates and components

**Conventions:**
- Every page extends `base.html` and uses `url_for`.
- Use token classes only, no inline `style`.
- Forms include `{{ form.hidden_tag() }}` or `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
- Use `flash_messages()` at the top of content.
- Errors use the `.form-error` style with `aria-invalid` / `aria-describedby` as in `components/form_field.html`.

**Navbar (`components/navbar.html`).** When `current_user and app_shell`, render the logo only, linking to `expenses.dashboard`. When logged in on non-app pages (landing), keep the Dashboard + Log out buttons, pointing at `expenses.dashboard`. Logged-out state is unchanged.

**`coming_soon.html`.** Use `back_url|default(url_for('main.landing'))` and `back_label|default('Back to home')`.

**`components/category_icon.html`** — `category_icon(category, size="md")`. A `.icon-circle` (`inline-flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-cream-dark text-lg`). For images: `<img src="{{ category.icon_url }}" alt="" width="36" height="36" loading="lazy" class="h-full w-full object-cover">`. For emoji: `<span aria-hidden="true">`. The category name is always next to the icon, so the icon is decorative. `size="lg"` gives `h-12 w-12 text-2xl` (detail page).

**`components/expense_row.html`** — `expense_row(expense, number)`:
```
<li><a href="{{ url_for('expenses.detail', expense_id=expense.id) }}" class="expense-row">
  <span class="hidden text-sm text-ink-soft sm:block">{{ number }}</span>
  <span class="flex min-w-0 items-center gap-3">{{ category_icon(expense.category) }}<span class="truncate font-semibold">{{ expense.category.name }}</span></span>
  <span class="text-right font-bold tabular-nums">{{ expense.amount|money }}</span>
  <span class="col-span-2 text-sm text-ink-soft sm:col-span-1 sm:text-right"><span class="sm:hidden">#{{ number }} · </span>{{ expense.spent_on|short_date }}</span>
</a></li>
```
`.expense-row` = `grid min-h-14 grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 rounded-2xl border border-transparent bg-white px-4 py-3 shadow-soft transition duration-150 hover:-translate-y-0.5 hover:border-cream-dark sm:grid-cols-[2.5rem_1fr_9rem_7rem] sm:px-5`. Mobile is two lines (icon + name + amount, then "#3 · Sat, 21 Nov"); desktop is 4 columns (No. | Category | Amount | Date).

**`components/top_bar.html`** — `top_bar(view)`. Heading `Your {{ accent("month.") }}`, then a `flex flex-wrap items-center gap-2 sm:gap-3` row, left → right:
1. **Month form**:
   - `<form method="get" action="{{ url_for('expenses.dashboard') }}" data-autosubmit>` with a `<label class="sr-only" for="month">Month</label>`.
   - `<select id="month" name="month" class="select-pill">` with options from `view.month_options` and the selected month marked `selected`.
   - `<noscript><button class="btn-ghost btn-sm">Go</button></noscript>`.
   - It has no `day` field, so changing the month clears the day.
2. **Day form**:
   - `<form method="get" data-autosubmit>` with a hidden `month` (when not current) and `<label class="sr-only" for="day">Day</label>`.
   - `<input type="date" id="day" name="day" min="{{ view.date_min }}" max="{{ view.date_max }}" value="{{ view.day or '' }}" class="form-input w-auto py-2 text-sm">`.
   - With no day: `<span class="text-sm text-ink-soft">All days</span>`. With a day: `<a class="btn-ghost btn-sm" href="(month only)">× All days</a>`.
   - Noscript Go button.
3. **Analytics**: `{{ button("Analytics", url_for('placeholders.analytics'), "ghost", extra="btn-sm") }}` with the `chart` icon.
4. **Spent tab**:
   - `<div class="card-dark spent-tab order-last w-full sm:order-none sm:ml-auto sm:w-auto">`.
   - Contents: "Spent in {{ view.today|month_name }}", the big `{{ view.totals.month_to_date|money }}` (`text-2xl font-extrabold`), and "till {{ view.today|day_month }}" (`text-xs text-cream/70`).
   - `.spent-tab` = `px-5 py-3 sm:p-4` (overrides the card padding).
5. **Profile**: `{% include "components/profile_menu.html" %}` with `ml-auto sm:ml-0` (on mobile it sits at the right of the first row).

At 375px: row 1 has Month, Day and the profile circle; row 2 has Analytics (wrapped); then the spent strip at full width. Check there's no horizontal scroll; the selects and date input must be able to shrink (`min-w-0`).

**`components/profile_menu.html`**:
- `<details class="relative" data-profile-menu>`.
- `<summary class="avatar" aria-label="Profile menu">{{ current_user.initial }}</summary>`, with `.avatar` = `flex h-10 w-10 cursor-pointer list-none items-center justify-center rounded-full bg-ink font-semibold text-cream [&::-webkit-details-marker]:hidden`.
- Panel: `absolute right-0 z-30 mt-2 w-64 rounded-2xl bg-white p-4 shadow-soft` containing the name (`font-semibold`), the email (`text-sm text-ink-soft break-all`), a "Manage categories" link (`categories.index`) and `{{ logout_button("dark", "btn-sm w-full") }}`.
- It works without JS (native details); JS adds outside-click and Esc to close.

**`components/expense_form.html`** — `expense_form(form, categories, action, submit_label, in_dialog=False, cancel_url=None)`, shared by the add panel and the edit page:
- `<form method="post" action="{{ action }}" class="space-y-5" novalidate>` + `form.hidden_tag()` (includes return_month/return_day).
- **Amount**: label, then a `relative` wrapper with `<span class="pointer-events-none absolute inset-y-0 left-4 flex items-center font-semibold text-ink-soft">Rs</span>` and `{{ form.amount(class="form-input pl-12", inputmode="decimal", type="number", step="0.01", min="0.01", autocomplete="off") }}`, plus its error.
- **Category**:
  - `<fieldset>` with `<legend class="form-label">Category</legend>`.
  - Grid `grid max-h-56 grid-cols-2 gap-2 overflow-y-auto pr-1 sm:grid-cols-3`. It scrolls, so **any number of categories** fits.
  - For each category: `<label class="category-chip"><input type="radio" name="category_id" value="{{ c.id }}" class="sr-only" {% if form.category_id.data == c.id %}checked{% endif %}>{{ category_icon(c) }}<span class="truncate">{{ c.name }}</span></label>`.
  - The last chip is `<a class="category-chip border-dashed" href="{{ url_for('categories.index') }}">+ New category</a>`.
  - `.category-chip` = `flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border border-cream-dark bg-white px-3 py-2 text-sm font-medium hover:bg-cream has-checked:border-ink has-checked:bg-cream-dark has-focus-visible:outline-2 has-focus-visible:outline-ember`.
  - Then the error.
- **Date**: `{{ form.spent_on(type="date", max=today_iso, class="form-input", data_day_input=True) }}`, then `<p class="mt-1.5 text-sm text-ink-soft" data-day-name>{{ parsed date|day_name }}</p>` (rendered on the server, updated by JS), then the error.
- **Note**: `{{ form.note(class="form-input min-h-24", maxlength="500", rows="3", data_char_input=True) }}`, then `<p class="mt-1.5 text-right text-xs text-ink-soft"><span data-char-count>{{ (form.note.data or '')|length }}</span>/500</p>`, then the error.
- **Buttons**:
  - `<button type="submit" class="btn-primary w-full">{{ submit_label }}</button>`.
  - Cancel: if `in_dialog`, `<button type="button" class="btn-ghost w-full" data-close-dialog>Cancel</button>`; otherwise `<a class="btn-ghost w-full" href="{{ cancel_url }}">Cancel</a>`.
- The route passes `today_iso` (Karachi). With no categories (e.g. a load error), show "Couldn't load your categories." with a link to `/categories`.

**`components/confirm_dialog.html`** — `confirm_dialog(id, title, message, action, confirm_label="Delete")`:
- A trigger `<button type="button" hidden data-js-only data-open-dialog="{{ id }}" class="…">` (passed in by the caller via `caller()` or a label param).
- A `<noscript>` fallback: a direct POST form with the same button text.
- `<dialog id="{{ id }}" class="dialog-confirm" aria-labelledby="{{ id }}-title">` containing `<div class="p-6">`, an `h2`, the message `p`, and a `flex justify-end gap-2` row with `<button type="button" class="btn-ghost btn-sm" data-close-dialog>Cancel</button>` and a `<form method="post" action="{{ action }}">` (CSRF + `<button class="btn-primary btn-sm">{{ confirm_label }}</button>`).
- `.dialog-confirm` = `m-auto w-[calc(100%-2rem)] max-w-sm rounded-2xl bg-white p-0 text-ink shadow-soft backdrop:bg-ink/50`.

**`dashboard.html`**:
- `flash_messages()`, then `top_bar(view)`.
- **List header** (`mt-8`):
  - Day selected → `<p>Showing {{ view.day|short_date }} · {{ view.totals.view_total|money }} that day</p>`.
  - Otherwise → `<h2>{{ view.month|month_label }}</h2>`; for a past month, also `<p class="text-ink-soft">Total for {{ view.month|month_label }}: {{ view.totals.view_total|money }}</p>`.
- `<ol class="mt-4 space-y-3 pb-28">` with `{% for e in view.expenses %}{{ expense_row(e, loop.index) }}{% endfor %}`.
- **Empty states** (in a `card text-center text-ink-soft`):
  - day → "Nothing spent on {{ view.day|short_date }}."
  - current month → "No expenses yet this month. Tap + to add your first one."
  - past month → "No expenses in {{ view.month|month_label }}." (D8)
- **FAB**: `<a href="{{ url_for('expenses.dashboard', add=1, **params) }}" class="fab" data-open-dialog="add-expense" aria-label="Add expense">{{ icon("plus", "h-7 w-7") }}</a>`, with `.fab` = `fixed right-5 bottom-5 z-20 inline-flex h-14 w-14 items-center justify-center rounded-full bg-ember text-white shadow-soft hover:bg-ember-dark sm:right-8 sm:bottom-8`.
- **Add dialog**:
  - `<dialog id="add-expense" class="dialog-panel" aria-labelledby="add-expense-title" {% if open_add %}open data-auto-open{% endif %}>` containing `<div class="p-5 sm:p-6">`, a header row with `h2` "Add expense" and an × button (`data-close-dialog aria-label="Close"`), then `expense_form(form, categories, url_for('expenses.create_expense'), "Save expense", in_dialog=True)`.
  - `.dialog-panel` = `mx-0 mt-auto mb-0 max-h-[90vh] w-full max-w-full overflow-y-auto rounded-t-3xl bg-white p-0 text-ink shadow-soft backdrop:bg-ink/50 sm:mt-auto sm:mr-6 sm:mb-6 sm:ml-auto sm:w-[480px] sm:max-w-[calc(100%-3rem)] sm:rounded-3xl`. That's a bottom sheet on mobile and anchored bottom-right on desktop. Check it in the browser, since UA dialog styles differ.
- Scripts: `dialogs.js`, `dashboard.js`, `expense-form.js`.

**`expenses/detail.html`**:
- `section.container-page py-8`, a back link `← Back to dashboard` (to the expense's month), then `card mx-auto max-w-3xl sm:p-8`.
- Inside, `grid gap-6 sm:grid-cols-[1fr_auto]`:
  - **Left**: amount `text-4xl font-extrabold sm:text-5xl`; the category (icon lg + name); `long_date`.
  - **Right**: `flex flex-col gap-2 sm:items-end`, with Edit (`btn-dark`, full width on mobile) and the Delete trigger (`btn-ghost text-ember-dark`, full width on mobile) via `confirm_dialog("delete-expense", "Delete this expense?", "This can't be undone.", url_for('expenses.delete_expense', …))`.
- **Note**: `.note-box` = `mt-6 rounded-xl bg-cream p-4 whitespace-pre-line`, showing the note or `<span class="text-ink-soft">No note added.</span>`. Autoescape stays on.
- At 375px the columns stack and the buttons are `w-full sm:w-auto`. Script: `dialogs.js`.

**`expenses/edit.html`**: a back link to the detail page, then `card mx-auto max-w-lg`, `h1` "Edit expense", and `expense_form(form, categories, url_for('expenses.edit', …), "Save changes", cancel_url=detail)`. Script: `expense-form.js`.

**`categories/index.html`**:
- Back link to the dashboard, then `h1` "Your {{ accent('categories.') }}".
- `grid gap-6 lg:grid-cols-[1fr_380px]`.
- **List** `ul.space-y-3` (no limit). Each item is a white rounded row with:
  - the icon and name
  - a `.badge` "Default" (`rounded-full bg-cream-dark px-2 py-0.5 text-xs font-semibold text-ink-soft`) when `is_default`
  - "{n} expenses" (`text-sm text-ink-soft`)
  - an Edit link (`?edit=id#category-form`)
  - Delete via `confirm_dialog("delete-cat-{{ c.id }}", "Delete {{ c.name }}?", n > 0 ? "{n} expenses will move to {fallback name}." : "This can't be undone.", …)`; the message strings are built in the route/service, not the template. **No Delete for `is_fallback`.**
- **Form card** `id="category-form"`:
  - Title "Add a category", or "Edit {name}" with a "Cancel edit" link.
  - `<form method="post" enctype="multipart/form-data" action="create or update url">` with `hidden_tag`, then the name `field()`, then the icon-type radios (two pills: Emoji / Upload photo).
  - Emoji grid: `grid grid-cols-6 gap-2`, each `<label class="emoji-chip"><input type="radio" name="emoji" value="🍔" class="sr-only">🍔</label>`, with `.emoji-chip` = `flex h-11 items-center justify-center rounded-xl border border-cream-dark text-xl cursor-pointer has-checked:border-ink has-checked:bg-cream-dark`. Pre-check the current emoji when editing, or the first one.
  - Photo: `<input type="file" name="photo" accept="image/*" class="…">`, a preview `<img data-icon-preview hidden class="h-16 w-16 rounded-full object-cover">` (shows the current image when editing), the hint "JPG, PNG or WEBP, up to 2 MB.", and errors.
  - Submit: `btn-primary w-full`.
  - Both icon sections stay visible (no JS needed); the radio decides which one is used.
- Scripts: `dialogs.js`, `category-form.js`.

**JS (vanilla, small, all optional):**
- **`dialogs.js`**:
  - un-hide every `[data-js-only]` element (remove its `hidden` attribute); `<noscript>` fallbacks don't render when JS is on, so leave them alone
  - `[data-open-dialog]` click → `preventDefault()`, remember `document.activeElement`, `dialog.showModal()`
  - `[data-close-dialog]` click → `closest('dialog').close()`
  - a click on the dialog element itself (the backdrop area, since the content is wrapped in an inner padded div) → `close()`
  - the `close` event → focus the remembered opener
  - on load, for `dialog[data-auto-open]`: if it's `open`, call `close()` then `showModal()` (calling `showModal` on an open dialog throws), then focus the first `[aria-invalid="true"]` or the first input
  - If `HTMLDialogElement` is missing, do nothing (links fall back to `?add=1`).
- **`dashboard.js`**:
  - `form[data-autosubmit]` change → `form.requestSubmit()`.
  - `details[data-profile-menu]`: a document click outside removes `open`; Esc closes it and focuses the summary.
- **`expense-form.js`**:
  - `[data-day-input]` change → set `[data-day-name]` to `new Date(value + "T00:00").toLocaleDateString("en-GB", {weekday: "long"})`, or empty if invalid.
  - `[data-char-input]` input → update `[data-char-count]`.
- **`category-form.js`**: when the file input changes, show a preview via `URL.createObjectURL` and check the `icon_type=image` radio. Clicking an emoji checks `icon_type=emoji`. Optional client-side size hint (> 2 MB shows the error text early); the server still validates.

---

## 7. Implementation phases and checkpoints

| Phase | Work | Checkpoint (must pass before moving on) |
|---|---|---|
| 0 | Copy this plan to `technical-plan/`. Commit the spec + plans folder rename (`docs: spec 03 and plan; move plans to technical-plan/`). Add deps (step 1). | `pip install` ok; the PIL / Karachi import one-liner prints nothing and doesn't error |
| 1 | Supabase §2.1–2.6 | All §2.4 queries match; every §2.5 test behaves as stated; no new advisor findings; migration files committed |
| 2 | Steps 2–11 (config, client, utils, services, forms) | A scratchpad script (not committed) checks: `money(Decimal("1250"))=="Rs 1,250"`, `money(Decimal("99.5"))=="Rs 99.50"`, `money(Decimal("1234567.00"))=="Rs 1,234,567"`; `short_date(date(2026,11,21))=="Sat, 21 Nov"`; `long_date` → "Saturday, 21 November 2026"; month/day param parsing (bad format, future month, day outside month, future day → None); `process_icon` on a PNG, a JPEG with EXIF rotation, a WEBP, a text file renamed `.png` (IconError), and a > 2 MB file (IconError) → output is 128×128 WEBP |
| 3 | Steps 12–16 + `__init__`/`auth_utils` edits + minimal templates | `flask run --debug` starts; `flask routes` lists all §5 endpoints; login lands on `/dashboard`; `grep -r "auth.dashboard" app` finds nothing |
| 4 | Dashboard templates, CSS, `dialogs.js`/`dashboard.js`/`expense-form.js`; Tailwind watch running | Add 3 expenses (today, earlier this month, last month) → they appear newest first; month and day filters work; totals are right; validation errors keep the panel open |
| 5 | Detail, edit, delete | Edit changes persist; delete confirm works; another user's expense id → 404 |
| 6 | Categories page + storage | Create emoji and photo categories; rename "Other"; replace a photo (old object gone in Storage); delete a category with expenses (they move to the fallback) |
| 7 | 375px/a11y pass, `--minify` build, `vercel.json`, README, CLAUDE.md | Full §8 checklist locally, then on Vercel |

Commits: `feat(db): …`, `feat(core): dates utils, user client, services`, `feat(expenses): dashboard and add panel`, `feat(expenses): detail, edit, delete`, `feat(categories): manage categories and icon uploads`, `chore: analytics login-required, vercel excludes`, `docs: spec 03 readme and claude.md`. Each ends with the attribution line from the session.

---

## 8. Test plan (spec §12 acceptance criteria)

There's no committed test suite (CLAUDE.md). Use scratchpad scripts plus the Flask test client for pure and offline checks, `execute_sql` for DB checks, and the browser for the rest. Do it **locally and on Vercel**.

**Supabase**
- [ ] Migration files exist and are applied → `list_migrations` shows both; §2.4 (a)–(d).
- [ ] Columns, checks and indexes → §2.4 (a), (b) match §2.2.
- [ ] **Two-account RLS test:**
  1. §2.5 SQL impersonation.
  2. In the browser: account A (normal window) and account B (private window). As B, add an expense and a category, and copy the expense URL and category id.
  3. As A, open B's `/expenses/<id>`, `/expenses/<id>/edit`, and `/categories?edit=<B cat id>` → 404 / ignored.
  4. As A, POST to `/expenses/<B id>/delete` and `/categories/<B cat>/delete` (DevTools: edit a form's `action`) → 404.
  5. As A, change a category radio's `value` to B's category id in DevTools and submit the add form → "Please choose a category." and nothing inserted.
- [ ] New sign-up gets 7 defaults with one fallback → sign up account B and run §2.4 (e). The 3 existing users show 7/1.
- [ ] Bucket exists and writes are owner-folder only → §2.4 (f) + §2.5 storage test. After a photo upload, the object is at `{A id}/<hex>.webp`.

**Dashboard**
- [ ] Current-month list newest first (`spent_on desc, created_at desc`): two expenses on the same day show the later-created one first. Each row shows No., icon + name, `Rs` amount and "Sat, 21 Nov".
- [ ] Month selector lists the first expense month (or signup month) through the current month, with no future months. Choosing October reloads with `?month=2026-10` and no `day`. Hand-typed `?month=2030-01`, `?month=abc`, `?month=2026-13` → default view, no error.
- [ ] Date picker: `min`/`max` limits are right (max = today in the current month). Picking a day filters the list and shows "Showing … · Rs X that day". "× All days" clears it. `?day=2026-10-05&month=2026-11` → ignored.
- [ ] "Spent this month": add an expense dated today and one dated last month → the tab counts only the current month through today. **Karachi check:** between 19:00 and 24:00 UTC (00:00–05:00 PKT), "today" is already the next day; verify by temporarily patching `karachi_today` in the scratch script, or check on Vercel at that time. On a past month, the tab still shows the current month, and "Total for October 2026: Rs X" appears.
- [ ] Analytics → coming-soon page with "← Back to dashboard". Logged out `/analytics` → login.
- [ ] Profile circle → menu with name, email, Manage categories, and Log out (a POST; `GET /logout` is 405).
- [ ] Empty states: new account → "No expenses yet this month. Tap + to add your first one."; a day with nothing → "Nothing spent on …"; an empty past month → "No expenses in …".
- [ ] With JS off: month/day "Go" buttons work; "+" goes to `?add=1` and the panel shows open; the profile menu opens.

**Add / view / edit / delete**
- [ ] "+" opens a bottom-right panel on desktop and a bottom sheet at 375px. ×, Esc and a backdrop click close it, and focus returns to "+". A valid save → "Expense added." and the row appears. Saving a last-month date while viewing the current month → redirects to last month.
- [ ] Validation keeps the panel open with values and inline errors: amount `0`, `-5`, `abc`, `1.234`, `10000000` → "Enter an amount greater than 0."; no category → "Please choose a category."; tomorrow's date → "Date can't be in the future."; 501-character note (sent via DevTools after removing `maxlength`) → "Note can be up to 500 characters."
- [ ] Clicking a row → detail page with amount, category, "Saturday, 21 November 2026", the note or "No note added.", and Edit / Delete.
- [ ] Edit saves ("Expense updated.", values changed). Delete → confirm dialog → "Expense deleted." and it's gone from the list. Cancel does nothing.
- [ ] Future dates and amounts ≤ 0 are rejected on both add and edit (also by the DB check: `amount <= 0` → 23514).

**Categories**
- [ ] Create with an emoji. Create with a JPG, PNG and WEBP photo → Storage object is 128×128 WEBP (download it and check). A `.txt` renamed `.jpg`, a 3 MB file (→ 413 handler message), and a GIF → "Upload a JPG, PNG or WEBP image under 2 MB."
- [ ] Rename "Food" → "Meals"; rename to an existing name in a different case ("transport") → "You already have a category with this name."; change a default's icon to a photo, then back to an emoji.
- [ ] **No limit:** create 15+ custom categories → all are listed, and the add-panel chip grid scrolls.
- [ ] Delete a category with 2 expenses → the dialog says "2 expenses will move to Other." → those expenses now show "Other". "Other" has no Delete button; POSTing its delete URL → "Other can't be deleted." Rename "Other" → "Misc" and delete another category → the expenses move to "Misc".
- [ ] Replacing a photo icon and deleting a photo category both remove the old object from Storage (check with `select name from storage.objects where bucket_id='category-icons'`).

**Quality**
- [ ] Remove the `csrf_token` input in DevTools and submit each POST (add, edit, delete expense, create/update/delete category) → "Your session timed out…" and a redirect, with no 405.
- [ ] Logged out, every new route → `/login?next=…`.
- [ ] `git grep -i service_role` shows only docs warnings, and no keys in the repo.
- [ ] 375px (DevTools iPhone SE) on dashboard, panel, detail, edit, categories and analytics: no horizontal scroll, the top bar wraps, the FAB doesn't cover the last row.
- [ ] Vercel: deploy, then repeat the add/edit/delete/photo upload. Function logs show no tracebacks.

**Automated checks worth keeping (scratchpad, not committed unless Daniyal asks to add pytest):** the Phase 2 pure-function checks, plus Flask test-client checks for `login_required` redirects, 404 for random UUIDs, CSRF rejection (with `WTF_CSRF_ENABLED` left on), and the 413 handler.

---

## 9. Risks, edge cases, deviations

**Deviations from the spec (with reasons)**

| # | Deviation | Reason |
|---|---|---|
| D1 | Extra column `categories.is_fallback` (+ partial unique index; delete policy excludes it) | Approved by Daniyal. Defaults (including "Other") can be renamed, so finding it by name breaks. |
| D2 | `expenses.category_id` FK uses NO ACTION, not RESTRICT | RESTRICT is checked immediately and can break the `auth.users` delete cascade (categories deleted before their expenses). NO ACTION is checked at the end of the statement: it still blocks deleting a used category and lets account deletion work. |
| D3 | Column-level grants, `user_id default auth.uid()`, nothing for `anon` | The JWT is readable from the signed cookie, so users could call PostgREST directly. This stops them setting `is_default`/`is_fallback`/`user_id`. |
| D4 | Totals come from the `dashboard_totals` SQL function (RPC), not PostgREST `amount.sum()` | PostgREST aggregates are off by default on Supabase. This is still a database `sum()`, and one round trip. |
| D5 | Extra own-folder SELECT policy on `storage.objects`; bucket limited to `image/webp`, 512 KB | Storage only deletes objects the caller can select (otherwise `remove` silently returns `[]`). The limits are defence in depth. |
| D6 | "Signup month" = earliest category `created_at` (seeded with `auth.users.created_at`) | The app can't read `auth.users` with the anon key. This needs no security-definer function. |
| D7 | After adding, the day filter is kept only if the new expense is on that day | Otherwise the new expense would be hidden right after saving. The month rule follows the spec. |
| D8 | Extra messages: "Please choose a valid date.", "Category name must be 1–30 characters.", "Please choose an emoji.", empty state for a past month | The spec gives no text for these cases. |
| D9 | `coming_soon.html` takes `back_url`/`back_label`; Analytics copy per spec §7.6 | Needed for "← Back to dashboard". |
| D10 | No-JS fallbacks: `?add=1` opens the panel; delete confirms degrade to a direct POST button in `<noscript>` | Spec requires working with JS off; the native confirm needs JS. |
| D11 | New dependency `tzdata` | `zoneinfo` can't find Asia/Karachi on Windows (verified). |
| D12 | Seeding function in a non-exposed `private` schema | A security-definer function in `public` could be called through the API. |
| D13 | Extra DB checks (amount ≤ 9,999,999.99, note ≤ 500, trimmed name, icon path format) and FK index | Defence in depth; the advisor flags unindexed FKs. |
| D14 | Edit-category form is on `/categories?edit=<id>` (no extra GET route); "+ New category" links to `/categories` (no inline mini-form) | Keeps the spec's route table; the spec allows either. |

**Risks and edge cases**
- **Timezone:** use only `karachi_today()`. `date.today()`/`datetime.now()` without a tz is a bug (Vercel runs in UTC). The `created_at` tie-break is a UTC timestamp, which is fine for ordering.
- **Money:** never `float`. Read `amount::text`, parse RPC numerics with `Decimal(str(v))`, send amounts as strings.
- **Many rows:** PostgREST returns at most 1000 rows per request (one month of personal expenses won't reach it). Note it in the README; no pagination in this spec.
- **No category limit:** keep `list_categories()` unlimited (≤ 1000 by PostgREST, effectively unbounded here). Don't add `.limit()`.
- **Orphaned icons:** if a Storage remove fails after a DB change, it's logged and the file stays. That's acceptable (small, public, non-sensitive). Upload-then-DB-failure cleans up the new file.
- **Expired token mid-request:** `before_request` refreshes with a 60s margin; a 401 from PostgREST maps to the generic message.
- **iOS photos:** `accept="image/*"` lets iOS convert HEIC to JPEG; if a HEIC still arrives, the user gets the friendly error.
- **`<input type="date">` min/max** aren't enforced by every mobile picker, so the server always re-validates.
- **Seeding trigger:** if it ever errors, sign-ups fail. It's simple, `search_path=''`, and tested in Phase 1 with a real sign-up.
- **Renamed "Other" + re-running seeding:** `on conflict do nothing` skips the duplicate fallback, so there's no error and no second "Other".
- **Category delete race:** `delete_category` locks the row (`for update`) and runs in one transaction.
- **Pillow on Vercel:** about 10 MB wheel, well within limits; check the first deploy's build log.

---

## 10. Deviations made during implementation

| # | Change | Reason |
|---|---|---|
| I1 | `components/top_bar.html` and `components/profile_menu.html` are `{% include %}` partials (they read `view`, `month_params` and `current_user` from the page context), not macros | Imported macros don't see context-processor variables such as `current_user`. |
| I2 | The profile menu is rendered twice in the top bar (one shown below `sm`, one from `sm` up) | It sits at the right of the heading on phones and next to the "Spent" tab on desktop. |
| I3 | `expense_form(...)` takes `today_iso` as an explicit argument; added the `iso_day_name` Jinja filter | Macros can't read the page context; the weekday under the date field is rendered by Python. |
| I4 | Added `DashboardView.month_value` / `day_value` properties, `services.expenses.empty_view()` and a `month_params` template variable | Keeps `strftime` and fallback logic out of the templates; lets the dashboard still render when the database can't be reached. |
| I5 | Phases 3–6 (routes, templates, JS) were written together, then verified with the offline route checks, and committed in logical pieces | The templates and routes depend on each other. |
| I6 | `CategoryRow` dataclass in `routes/categories.py` builds the per-category delete-dialog message | The plan said strings are built in the route, not the template. |
