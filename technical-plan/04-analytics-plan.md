# Spec 04 — Analytics: Technical Implementation Plan

> **Step 0 of implementation:** copy this file to `technical-plan/04-analytics-plan.md` (plan mode only allows writing here). The plan is written so an implementer with no access to the planning conversation can follow it literally. Where it says "verify", run the check.

---

## 0. Context

Specs 01–03 are done. `/analytics` is still a coming-soon page served by `app/routes/placeholders.py`. Spec 04 (`specs/04-analytics-spec.md`, **read it fully first**) replaces it with a real one-month analytics page: a month picker, 4 stat cards and 4 Chart.js charts. The page has to work from 375px to desktop, and stay usable without JS.

**Facts checked during planning (2026-11-22):**
- **Chart.js latest 4.x = 4.6.1.** cdnjs file `chart.umd.min.js`, SRI `sha512-vMRyUfXe50uUhhDC+fk6UYBA/1VPj+I7Jn+wK0A3+wSVeUgT9OCz/xoF2M8KFvrmUOlb4Anv0FQUw8NafuzYPw==` (from `api.cdnjs.com/libraries/Chart.js/4.6.1?fields=sri`). **Don't use** the unversioned top-level `sri` field: it is the hash of `chart.min.js`, a different file. Re-verify the hash locally in step 0 (§4.1).
- **Chart.js docs:** responsive charts need a **relatively positioned container dedicated to one canvas**. With `maintainAspectRatio: false`, the height comes from that container. Never style the canvas itself. `onClick(event, elements, chart)` runs on click. Default `events` are `['mousemove','mouseout','click','touchstart','touchmove']`, so on a tap `touchstart` shows the tooltip and then `click` fires.
- **Installed `postgrest==2.34.1`:** `client.rpc(func: str, params: dict, count=None, head=False, get=False)`, then `.execute().data`. This is the same call style as `dashboard_totals()` in `app/services/expenses.py:156`. A function returning `jsonb` comes back with `.data` = the decoded JSON value (a dict). **JSON numbers decode to Python `float`**, so money is returned as **text** (deviation D1).
- On Supabase, new functions in `public` get `EXECUTE` for `anon` by default privileges, so **`revoke ... from public, anon` is required** (this matches the Spec 03 migration).
- Tailwind scans **only `app/templates`** (`@source "../templates"`). Classes that appear only in JS are never generated, so `analytics.js` adds no Tailwind classes.
- `request.blueprint in {...}` in `app/__init__.py:67` decides `app_shell` (hides marketing nav links). The new blueprint must be added there.

**Decisions confirmed with Daniyal:**
- The shared month picker shows **‹ › arrows on both the dashboard and analytics**.
- Testing uses **2 existing accounts**. Before seeding, ask Daniyal which two (A = main test account, B = RLS check). All seeded expenses get the note prefix `[seed-04]`. Delete them only with his approval.

---

## 1. Summary

**Delivers**
- Migration `20261122_03_analytics_function.sql`: `public.get_month_analytics(p_month_start date, p_today date) returns jsonb`, plus its grants.
- `/analytics?month=YYYY-MM` in a new `analytics` blueprint: header (← Dashboard, "Your *spending.*", ‹ month ▾ ›, profile menu), 4 stat cards, donut + HTML legend, daily bars (click → dashboard day), cumulative this-vs-last month, last-6-months bars (click → that month), empty/edge states, `<details>` data tables, aria summaries, noscript note.
- Shared `components/month_picker.html` used by the dashboard top bar and analytics. The dashboard gains arrows, and its Analytics button keeps `?month=`.
- `public/static/js/analytics.js`: palette, money helpers, the 4 charts, tap-to-follow.
- `placeholders.py` and `coming_soon.html` are deleted (their docstring says to delete them once `/analytics` is real). The CSS is rebuilt, and README and CLAUDE.md are updated.

**Out of scope:** top-5 list, weekday chart, budgets, custom ranges, export/print, category drill-down.

### Deviations from the spec (with reasons)

| # | Deviation | Why |
|---|---|---|
| D1 | Money values in the RPC JSON are **strings** (`"6450.00"`), not numbers | JSON numbers become Python `float`. CLAUDE.md bans float for money. `Decimal("6450.00")` is exact, and JS reads them with `Number()` |
| D2 | `daily` / `prev_daily` entries also carry `running` (a window `sum()` in SQL). JS uses it instead of adding | The no-JS "Show data" table for chart 3 needs running totals, and Flask may not add. JS still adds the "Everything else" slice (plain adding, as §7.5 allows) |
| D3 | Extra keys: `first_month`, `prev.window_end`. The SQL **clamps** a month before `first_month` (or after the current month) to the current month | Keeps one round trip, and the page needs the lower bound for the dropdown and the ‹ arrow |
| D4 | JS gets a shaped `chart_data` payload (labels, URLs, percents, biggest-day index) built in Python, not the raw RPC JSON | Dates are formatted by the same Python filters as Jinja, and URLs come from `url_for()`. JS does no date or URL logic |
| D5 | Stats are 2×2 below **768px** (`md`) and 4 in a row from 768px | 4 cards at 640px leave ~84px per card, too tight for "Rs 1,234,567". The spec allows 2×2 on tablets |
| D6 | JS lives at `public/static/js/analytics.js` (the spec's tree says `app/static`) | CLAUDE.md: never create `app/static/` |
| D7 | The cumulative tooltip is multi-line: title "Day 22", then "Nov Rs 6,450" / "Oct Rs 5,760" | A single long line overflows on phones |
| D8 | The Daily average card shows whole rupees (half-up), e.g. 293.18 → "Rs 293" | Matches the spec example. The exact value stays in the aria text |
| D9 | Categories that fall into "Everything else" get its grey dot in the legend. Only palette colours 1–6 are used in the donut. Colours 7–8 are defined but unused | The dot colour has to match the slice the category is drawn in |
| D10 | Previous month has data but the comparison window total is 0 → "—" + "Nothing spent 1–22 Oct" (not "No data for October") | "No data" would be untrue |
| D11 | Biggest-day tie → the **latest** day | Same rule as the biggest expense |
| D12 | Out-of-range `?month=` before the first month falls back to current. The dashboard is **unchanged** (it still allows such months) | Spec 04 says this "matches the dashboard", but the dashboard actually widens its dropdown instead. Only analytics changes |

---

## 2. Supabase change (apply and verify FIRST)

### 2.1 Order
1. Write `supabase/migrations/20261122_03_analytics_function.sql` (§2.2).
2. Apply it with `mcp__supabase__apply_migration`, name `20261122_03_analytics_function`, query **byte-identical** to the file.
3. Run §2.3 checks (catalog, privileges, anon, impersonation, edge inputs), then seed (§8.1), then §2.4 (manual comparison + two-account test), then §2.5 advisors.
4. Commit: `feat(db): get_month_analytics RPC for the analytics page`.

**Destructive operations: none.** It is a `create or replace` of a new function, and no table changes. Rollback (only with Daniyal's OK): `drop function public.get_month_analytics(date, date);`.

### 2.2 `supabase/migrations/20261122_03_analytics_function.sql`

```sql
-- Spec 04: get_month_analytics(), everything the analytics page needs in one round trip.
-- security invoker: RLS on expenses/categories applies as the calling user (auth.uid()).
-- Money is returned as text (exact numeric, never a JSON float).

create or replace function public.get_month_analytics(p_month_start date, p_today date)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_uid         uuid := (select auth.uid());
  v_current     date;
  v_first       date;
  v_month       date;
  v_month_end   date;
  v_is_current  boolean;
  v_days_in     integer;
  v_days        integer;   -- days_elapsed
  v_to          date;      -- last counted day of the selected month
  v_prev        date;
  v_prev_end    date;
  v_prev_days   integer;
  v_window_end  date;
  v_six_from    date;
  v_total       numeric;
  v_count       bigint;
  v_prev_window numeric;
  v_prev_full   numeric;
  v_prev_count  bigint;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;
  if p_today is null then
    raise exception 'p_today_required' using errcode = '22004';
  end if;

  v_current := date_trunc('month', p_today::timestamp)::date;

  -- First available month: the same rule as dashboard_totals().first_month.
  v_first := date_trunc('month', least(
    (select min(e.spent_on) from public.expenses e where e.user_id = v_uid),
    (select (min(c.created_at) at time zone 'Asia/Karachi')::date
       from public.categories c where c.user_id = v_uid),
    p_today
  )::timestamp)::date;

  -- Out-of-range month -> current month. Flask already rejects bad formats and future months.
  v_month := date_trunc('month', coalesce(p_month_start, v_current)::timestamp)::date;
  if v_month < v_first or v_month > v_current then
    v_month := v_current;
  end if;

  v_month_end  := (v_month + interval '1 month')::date - 1;
  v_is_current := v_month = v_current;
  v_days_in    := extract(day from v_month_end)::integer;
  v_days       := case when v_is_current then extract(day from p_today)::integer else v_days_in end;
  v_to         := v_month + (v_days - 1);

  v_prev       := (v_month - interval '1 month')::date;
  v_prev_end   := v_month - 1;
  v_prev_days  := extract(day from v_prev_end)::integer;
  v_window_end := case when v_is_current
                       then v_prev + (least(v_days, v_prev_days) - 1)
                       else v_prev_end end;
  v_six_from   := greatest((v_month - interval '5 months')::date, v_first);

  select coalesce(sum(e.amount), 0), count(*)
    into v_total, v_count
    from public.expenses e
   where e.user_id = v_uid and e.spent_on between v_month and v_to;

  select coalesce(sum(e.amount) filter (where e.spent_on <= v_window_end), 0),
         coalesce(sum(e.amount), 0),
         count(*)
    into v_prev_window, v_prev_full, v_prev_count
    from public.expenses e
   where e.user_id = v_uid and e.spent_on between v_prev and v_prev_end;

  return jsonb_build_object(
    'month',            to_char(v_month, 'YYYY-MM'),
    'first_month',      to_char(v_first, 'YYYY-MM'),
    'is_current_month', v_is_current,
    'days_in_month',    v_days_in,
    'days_elapsed',     v_days,
    'total',            v_total::text,
    'count',            v_count,
    'daily_average',    round(v_total / v_days, 2)::text,

    'biggest', (
      select jsonb_build_object(
               'id', e.id, 'amount', e.amount::text, 'spent_on', e.spent_on,
               'category_name', c.name, 'icon_type', c.icon_type, 'icon_value', c.icon_value)
        from public.expenses e
        join public.categories c on c.id = e.category_id
       where e.user_id = v_uid and e.spent_on between v_month and v_to
       order by e.amount desc, e.spent_on desc, e.created_at desc
       limit 1
    ),

    'prev', jsonb_build_object(
      'month',        to_char(v_prev, 'YYYY-MM'),
      'has_data',     v_prev_count > 0,
      'window_end',   v_window_end,
      'window_total', v_prev_window::text,
      'full_total',   v_prev_full::text
    ),

    'by_category', coalesce((
      select jsonb_agg(jsonb_build_object(
               'category_id', s.id, 'name', s.name,
               'icon_type', s.icon_type, 'icon_value', s.icon_value,
               'total', s.total::text, 'count', s.n)
             order by s.total desc, s.name)
        from (
          select c.id, c.name, c.icon_type, c.icon_value, sum(e.amount) as total, count(*) as n
            from public.expenses e
            join public.categories c on c.id = e.category_id
           where e.user_id = v_uid and e.spent_on between v_month and v_to
           group by c.id, c.name, c.icon_type, c.icon_value
        ) s
    ), '[]'::jsonb),

    'daily', (
      select jsonb_agg(jsonb_build_object('day', x.day, 'total', x.total::text, 'running', x.running::text)
                       order by x.day)
        from (
          select g.i + 1 as day,
                 coalesce(t.total, 0) as total,
                 sum(coalesce(t.total, 0)) over (order by g.i) as running
            from generate_series(0, v_days - 1) as g(i)
            left join (
              select e.spent_on, sum(e.amount) as total
                from public.expenses e
               where e.user_id = v_uid and e.spent_on between v_month and v_to
               group by e.spent_on
            ) t on t.spent_on = v_month + g.i
        ) x
    ),

    'prev_daily', case when v_prev_count = 0 then '[]'::jsonb else (
      select jsonb_agg(jsonb_build_object('day', x.day, 'total', x.total::text, 'running', x.running::text)
                       order by x.day)
        from (
          select g.i + 1 as day,
                 coalesce(t.total, 0) as total,
                 sum(coalesce(t.total, 0)) over (order by g.i) as running
            from generate_series(0, v_prev_days - 1) as g(i)
            left join (
              select e.spent_on, sum(e.amount) as total
                from public.expenses e
               where e.user_id = v_uid and e.spent_on between v_prev and v_prev_end
               group by e.spent_on
            ) t on t.spent_on = v_prev + g.i
        ) x
    ) end,

    'six_months', (
      select jsonb_agg(jsonb_build_object('month', to_char(g.m, 'YYYY-MM'),
                                          'total', coalesce(t.total, 0)::text)
                       order by g.m)
        from generate_series(v_six_from::timestamp, v_month::timestamp, interval '1 month') as g(m)
        left join (
          select date_trunc('month', e.spent_on::timestamp)::date as month, sum(e.amount) as total
            from public.expenses e
           where e.user_id = v_uid and e.spent_on between v_six_from and v_to
           group by 1
        ) t on t.month = g.m::date
    )
  );
end;
$$;

comment on function public.get_month_analytics(date, date) is
  'Spec 04 analytics for one month. security invoker (RLS applies). Money values are text.';

revoke all on function public.get_month_analytics(date, date) from public, anon;
grant execute on function public.get_month_analytics(date, date) to authenticated;
```

Notes: each query filters `user_id = v_uid` explicitly as well as relying on RLS. That is defence in depth, and it lets the queries use `expenses_user_spent_idx (user_id, spent_on desc, created_at desc)`. `::timestamp` casts keep `date_trunc` / `generate_series` independent of the session time zone. The selected month (including in `six_months`) is bounded by `v_to`, so its bar equals `total`.

### 2.3 Checks right after applying (`mcp__supabase__execute_sql`)

```sql
-- a) exists, invoker, stable, search_path pinned
select p.proname, p.prosecdef, p.provolatile, p.proconfig, p.proacl
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname = 'get_month_analytics';
-- expect prosecdef = false, provolatile = 's', proconfig = {search_path=""},
-- proacl contains authenticated=X and no "=X/" (PUBLIC) and no anon entry

-- b) privileges
select has_function_privilege('anon', 'public.get_month_analytics(date,date)', 'execute') as anon_exec,          -- false
       has_function_privilege('authenticated', 'public.get_month_analytics(date,date)', 'execute') as auth_exec; -- true

-- c) anon really can't call it (expect ERROR 42501 permission denied for function)
begin; set local role anon;
select public.get_month_analytics('2026-11-01', '2026-11-22');
rollback;

-- d) authenticated without a user id -> 'not_authenticated'
begin; set local role authenticated;
select public.get_month_analytics('2026-11-01', '2026-11-22');
rollback;
```

The impersonation template (used in §2.4 and for edge inputs):
```sql
begin;
select set_config('request.jwt.claims', json_build_object('sub', '<USER_ID>', 'role', 'authenticated')::text, true);
set local role authenticated;
select public.get_month_analytics('<MONTH_START>', '2026-11-22');
rollback;
```
Edge inputs to run as user A, with what to expect:
- `'2027-01-01'` (future) → `month` = `2026-11`.
- A month before `first_month` → `2026-11`.
- `'2026-10-15'` → `2026-10`.
- Current month → `days_elapsed = 22`, and `daily` has 22 entries.
- A past 31-day month → `days_elapsed = 31`.
- `first_month` → `prev.has_data = false`, `prev_daily = []`.

Also check a `2026-03-01` call as A with `p_today = '2026-03-31'`, to exercise the window cap (31 days vs February's 28 → `window_end = 2026-02-28`).

### 2.4 Manual comparison + two-account RLS test (after seeding, §8.1)

As `postgres` (bypasses RLS), for user A and a seeded past month (e.g. October 2026):
```sql
select sum(amount), count(*) from public.expenses
 where user_id = '<A>' and spent_on between '2026-10-01' and '2026-10-31';

select g.d::date, coalesce(sum(e.amount), 0)
  from generate_series('2026-10-01'::timestamp, '2026-10-31', '1 day') g(d)
  left join public.expenses e on e.user_id = '<A>' and e.spent_on = g.d::date
 group by g.d order by g.d;                                   -- zeros included

select c.name, sum(e.amount), count(*) from public.expenses e
  join public.categories c on c.id = e.category_id
 where e.user_id = '<A>' and e.spent_on between '2026-10-01' and '2026-10-31'
 group by c.name order by 2 desc, 1;

select date_trunc('month', spent_on::timestamp)::date, sum(amount) from public.expenses
 where user_id = '<A>' and spent_on between '2026-05-01' and '2026-10-31'
 group by 1 order by 1;
```
Compare each with the impersonated call for A: `total`, `count`, every `daily` entry (with zeros), `by_category` order and totals, `six_months` (including zero months), `biggest` (the highest amount, newest on a tie), and `daily_average = round(total/31, 2)`.

**Two-account test:** call as B for the same months.
- B's `total`/`count` must equal B's manual query.
- `biggest.id` must be one of B's expense ids.
- No B call may contain any of A's category ids. Check with `select count(*) from public.categories where id = any('{<ids from B json>}') and user_id <> '<B>'` → 0.
- Repeat with A and B swapped.

### 2.5 Advisors
Run `mcp__supabase__get_advisors` with `type: "security"` and `type: "performance"`. Expect no new findings for `get_month_analytics`. `function_search_path_mutable` is avoided by `set search_path = ''`. Write down any pre-existing findings in the summary, but don't fix them in this spec.

---

## 3. Files, in implementation order

### 3.1 `app/utils/dates.py` (change)
Add small helpers (with type hints). They are reused by the dashboard and analytics:
- `adjacent_months(month, first_month, current_month) -> tuple[date | None, date | None]`. Returns `(shift_month(month,-1) if month > month_start(first_month) else None, shift_month(month,1) if month < current_month else None)`.
- `month_from_value("2026-11") -> date` (for the `month` / `first_month` strings the RPC returns).
- `month_short(d) -> "Nov"`, `month_value(d) -> "2026-11"`.
- `day_range_label(start, end) -> "1–22 Oct"`, or `"1 Oct"` when start == end. It uses an en dash.
- `whole_money(value) -> "Rs 293"` (quantize to 0 with `ROUND_HALF_UP`, then `money`).

Register `month_short` and `whole_money` as filters too (add them to `register_filters`).

### 3.2 `app/templates/components/macros.html` (change)
Add `chevron-left` (`<path d="m15 18-6-6 6-6"/>`) and `chevron-right` (`<path d="m9 18 6-6-6-6"/>`) to `icon()`.

### 3.3 `app/templates/components/month_picker.html` (new)
```jinja
{#- ‹ Month ▾ › picker shared by the dashboard and analytics.
    Import: {% from "components/month_picker.html" import month_picker %}
    action: form URL; options: [(value, label)]; selected: "YYYY-MM"; prev_url/next_url: None = disabled. -#}
{% from "components/macros.html" import icon %}
{% macro month_picker(action, options, selected, prev_url=None, next_url=None, extra="") -%}
<div class="month-picker {{ extra }}">
  {% if prev_url %}<a href="{{ prev_url }}" class="month-arrow" aria-label="Previous month">{{ icon("chevron-left") }}</a>
  {% else %}<span class="month-arrow" role="link" aria-disabled="true" aria-label="Previous month">{{ icon("chevron-left") }}</span>{% endif %}
  <form method="get" action="{{ action }}" data-autosubmit class="min-w-0 flex-1 sm:flex-none">
    <label for="month" class="sr-only">Month</label>
    <select id="month" name="month" class="select-pill w-full sm:w-auto">
      {% for value, label in options %}<option value="{{ value }}"{% if value == selected %} selected{% endif %}>{{ label }}</option>{% endfor %}
    </select>
    <noscript><button type="submit" class="btn-ghost btn-sm">Go</button></noscript>
  </form>
  {% if next_url %}<a href="{{ next_url }}" class="month-arrow" aria-label="Next month">{{ icon("chevron-right") }}</a>
  {% else %}<span class="month-arrow" role="link" aria-disabled="true" aria-label="Next month">{{ icon("chevron-right") }}</span>{% endif %}
</div>
{%- endmacro %}
```
Auto-submit stays in `public/static/js/dashboard.js` (`form[data-autosubmit]`). Analytics loads that file too, which also gives it the profile-menu close-on-outside-click.

### 3.4 `app/styles/input.css` (change, in `@layer components`)
```css
/* Analytics + shared month picker (Spec 04) */
.month-picker { @apply flex w-full min-w-0 items-center gap-1 sm:w-auto; }
.month-arrow { @apply inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink transition-colors hover:bg-cream-dark; }
.month-arrow[aria-disabled="true"] { @apply cursor-not-allowed text-ink-soft/30 hover:bg-transparent; }
.stat-value { @apply mt-2 whitespace-nowrap font-extrabold leading-tight tracking-tight tabular-nums; }
.stat-value-lg { @apply text-[min(1.875rem,20cqw)]; }   /* ≤ 8 chars, e.g. "Rs 6,450" */
.stat-value-md { @apply text-[min(1.5rem,16cqw)]; }     /* ≤ 10 chars, "Rs 123,456" */
.stat-value-sm { @apply text-[min(1.25rem,13.5cqw)]; }  /* longer, "Rs 1,234,567" */
.chart-card { @apply flex min-w-0 flex-col; }
.chart-box { @apply relative h-56 w-full min-w-0 sm:h-60 lg:h-[280px]; }   /* 224 / 240 / 280px */
.donut-box { @apply relative h-[180px] w-[180px] shrink-0 lg:h-[200px] lg:w-[200px]; }
.legend-row { @apply grid grid-cols-[0.625rem_1.5rem_minmax(0,1fr)_auto_2.75rem] items-center gap-x-2 py-1.5 text-sm; }
.legend-dot { @apply h-2.5 w-2.5 rounded-full bg-cream-dark; }
.data-table { @apply w-full text-left text-sm tabular-nums [&_td]:py-1 [&_th]:py-1 [&_th]:font-semibold [&_th]:text-ink-soft; }
.chart-note { @apply mt-3 text-sm text-ink-soft; }
```
Stat cards use `card` / `card-dark` plus `@container min-w-0` in the template. `cqw` then scales the number to the card's own width, so it never overflows (§5.3).

### 3.5 `app/templates/components/category_icon.html` (change)
Add `size="sm"` → `h-6 w-6 text-sm` (image `width/height` 24). The legend and the Biggest card use it.

### 3.6 Dashboard: `app/services/expenses.py`, `components/top_bar.html` (change)
- `DashboardView`: add `first_month: date`. `build_dashboard` passes `min(totals.first_month, month)`, and `empty_view` passes `month`. Add properties `prev_month` / `next_month` via `adjacent_months(...)`.
- `top_bar.html`: replace the month `<form>` (lines 9–17) with:
  `{{ month_picker(url_for('expenses.dashboard'), view.month_options, view.month_value, url_for('expenses.dashboard', month=view.prev_month|month_value) if view.prev_month else None, url_for('expenses.dashboard', month=view.next_month|month_value) if view.next_month else None) }}`.
  Register `month_value` as a filter for this. The arrows drop `?day=`, which is intentional. The day picker form is unchanged.
- The Analytics link changes to `url_for('analytics.index', month=view.month_value)`.

### 3.7 `app/services/analytics.py` (new)
It calls the RPC and builds the view model. Python adds nothing. Only division (percents), comparison and max are done here.

```python
@dataclass(frozen=True)
class Icon:                      # what category_icon() needs
    icon_type: str; icon_value: str; icon_url: str | None

@dataclass(frozen=True)
class CategoryShare:
    id: str; name: str; icon: Icon; total: Decimal; count: int; pct: int   # pct of month total, half-up
    @property
    def pct_label(self) -> str: ...      # "42%" or "<1%" when 0 < share < 0.5%

@dataclass(frozen=True)
class DayPoint:   day: date; total: Decimal; running: Decimal
@dataclass(frozen=True)
class MonthPoint: month: date; total: Decimal; label: str; selected: bool   # label "Jun" / "Jan '27"
@dataclass(frozen=True)
class Biggest:    id: str; amount: Decimal; spent_on: date; category_name: str; icon: Icon
@dataclass(frozen=True)
class Comparison:
    direction: str | None         # "up" | "down" | "same" | None (no data)
    value: str                    # "▲ 12%", "▼ 8%", "0%", "<1%" variants, or "—"
    text: str                     # "vs 1–22 Oct (Rs 5,760)", "vs October (Rs 8,100)", "No data for October", "Nothing spent 1–22 Oct"

@dataclass(frozen=True)
class AnalyticsView:
    today: date; current_month: date; month: date; first_month: date; is_current_month: bool
    month_options: list[tuple[str, str]]; prev_month: date | None; next_month: date | None
    days_in_month: int; days_elapsed: int
    total: Decimal; count: int; daily_average: Decimal
    biggest: Biggest | None; comparison: Comparison
    prev_start: date; prev_has_data: bool
    categories: list[CategoryShare]; daily: list[DayPoint]; prev_daily: list[DayPoint]
    six_months: list[MonthPoint]; biggest_day: DayPoint | None
    aria: dict[str, str]          # "donut", "daily", "cumulative", "six"
    load_failed: bool = False
    # properties: month_value, has_expenses (count > 0), show_six_months (any total > 0 in six_months),
    #             stat sizes via stat_size(text) -> "lg" | "md" | "sm" (≤8 / ≤10 / longer chars)
```

Functions:
- `fetch_month_analytics(month: date, today: date) -> dict`. Runs `user_client().rpc("get_month_analytics", {"p_month_start": month.isoformat(), "p_today": today.isoformat()}).execute().data`. Wrap it in `except CAUGHT as error: raise friendly(error) from None`, and accept a dict or a one-item list. This is the same pattern as `expenses.dashboard_totals`.
- `build_analytics(month_param: str | None) -> AnalyticsView`. Steps: `today = karachi_today()`, `current = month_start(today)`, `requested = parse_month_param(month_param, current) or current`, then call the RPC. Take `month = month_from_value(data["month"])` (the SQL may have clamped it), `first = month_from_value(data["first_month"])`, `month_options(first, current)` and `adjacent_months(month, first, current)`. Convert every money string with `to_decimal`. Image icons get `storage.icon_url(icon_value)`.
  - Comparison: if `not prev.has_data` → `"—"`, "No data for {Prev}". Else if `window_total == 0` → `"—"`, "Nothing spent {1–22 Oct}". Otherwise `pct = ((total - window) / window * 100)`, quantized half-up; the arrow comes from the sign of `total - window`. The text is "vs {day_range_label(prev_start, window_end)} ({money(window)})" for the current month, and "vs {October} ({money(full)})" for a past month.
  - `biggest_day = max(daily, key=(total, day))` when `total > 0` (a tie goes to the latest day).
  - Six-month labels: `month_short`, with `" 'yy"` added to January only when `six_months[0].year != six_months[-1].year`.
  - Aria strings (§7.1).
- `chart_payload(view) -> dict` (D4). It uses `url_for` and runs in the request context:
  ```
  { "month_short": "Nov", "prev_short": "Oct", "total": "6450.00", "has_prev": true,
    "categories": [{"name": "Food", "total": "2700.00", "pct": 42}],
    "daily": [{"day": 1, "total": "0", "running": "0", "label": "Sun, 1 Nov",
               "url": "/dashboard?month=2026-11&day=2026-11-01"}],
    "biggest_day_index": 20,
    "prev_daily": [{"day": 1, "running": "120.00"}],
    "six_months": [{"label": "Jun", "title": "June 2026", "total": "7200.00",
                    "url": "/analytics?month=2026-06", "selected": false}] }
  ```
  Decimals are sent as `str(d)`. Never `float`.
- `empty_view(month_param) -> AnalyticsView`. Makes no network call: zeros, `month_options(month, current)`, `load_failed=True`.

### 3.8 `app/routes/analytics.py` (new), `app/routes/__init__.py`, `app/__init__.py` (change)
```python
"""Analytics page (Spec 04). Thin: call app.services.analytics and render."""
analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/analytics")
@login_required
def index():
    try:
        view = analytics_service.build_analytics(request.args.get("month"))
    except DataError as error:
        flash(error.user_message, "error")
        view = analytics_service.empty_view(request.args.get("month"))
    return render_template("analytics.html", view=view, chart_data=analytics_service.chart_payload(view))
```
- `routes/__init__.py`: export `analytics_bp` and remove `placeholders_bp`.
- `app/__init__.py`: register `analytics_bp` and drop `placeholders_bp`. In `app_shell`, change the set to `{"expenses", "categories", "analytics"}`.

### 3.9 Delete `app/routes/placeholders.py` and `app/templates/coming_soon.html`
Nothing else references them. Grep for `placeholders` / `coming_soon` (only `app/__init__.py`, `routes/__init__.py`, `top_bar.html`, README and CLAUDE.md, all updated in this plan). Both can be recovered from git.

### 3.10 `app/templates/components/stat_card.html` (new)
`stat_card(label, value, sub, size="lg", dark=False, href=None, value_class="")`. The root is `<a>` when `href` is set (Biggest card → `/expenses/<id>`, with hover lift like `expense-row`), otherwise `<div>`. Classes are `{{ 'card-dark' if dark else 'card' }} @container min-w-0`. The label is `text-xs font-semibold uppercase tracking-wide` (`text-cream/70` when dark, `text-ink-soft` otherwise). An optional `caller()` slot puts the category icon on the right of the label row, so it doesn't take value width. The value uses `stat-value stat-value-{{ size }} {{ value_class }}`, and the sub text is `mt-1 text-xs` (truncated).

### 3.11 `app/templates/components/chart_card.html` (new)
- `chart_card(heading, id)` → `<section class="card chart-card" aria-labelledby="{{ id }}-heading"><h2 id="{{ id }}-heading" class="font-semibold">…</h2>{{ caller() }}</section>`
- `chart_canvas(id, aria_label, box="chart-box mt-4")` → `<div class="{{ box }}"><canvas id="{{ id }}" role="img" aria-label="{{ aria_label }}"></canvas></div>`. The div is dedicated to the canvas, as Chart.js requires.
- `data_table(caption, headers)` → `<details class="mt-auto pt-4"><summary class="cursor-pointer text-sm font-semibold text-ink-soft">Show data</summary><div class="mt-2 max-h-72 overflow-y-auto"><table class="data-table"><caption class="sr-only">…</caption><thead><tr>{th scope=col…}</tr></thead><tbody>{{ caller() }}</tbody></table></div></details>`

### 3.12 `app/templates/analytics.html` (new)
It extends `base.html`. Title: "Analytics · Pocketly".

- **Header** (one flex-wrap block, a single profile-menu include, §5.2).
- `{% if view.has_expenses %}`:
  - noscript note + hidden `[data-chart-error]` paragraph ("Charts couldn't load. The numbers below are still correct.").
  - **Stats grid** (`mt-6 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4 lg:gap-6`):
    - Total spent: dark, `"{count} expense(s)"`
    - Daily average: `view.daily_average|whole_money`, "over {n} day(s)"
    - Biggest expense: href, icon slot, "Food · Sat, 21 Nov"
    - vs last month: `value_class` = `text-ember-dark` for up (ember on white is ~3.9:1; ember-dark passes AA for text), `text-ink` for down/same
  - **Charts grid** (`mt-4 grid grid-cols-1 gap-4 sm:mt-6 lg:grid-cols-2 lg:gap-6`), in this order: donut, daily, cumulative, six.
    - **Donut card:** `flex flex-col items-center gap-5 sm:flex-row sm:items-start`. Left: `relative` wrapper → `chart_canvas('chart-donut', …, box='donut-box')` + an absolute `pointer-events-none inset-0 flex flex-col items-center justify-center` overlay ("Rs 6,450" bold, "total" small). Right: `<ul class="w-full min-w-0 sm:flex-1">`, one `legend-row` per category: `<span class="legend-dot" data-legend-index="{{ loop.index0 }}">`, the icon (sm), name `truncate`, amount `text-right font-semibold`, pct `text-right text-ink-soft`. Data table: Category / Amount / Share.
    - **Daily card:** canvas `chart-daily`, note "Biggest day: Sat, 21 Nov — Rs 1,450". Table: Day (a link to the dashboard day) / Amount.
    - **Cumulative card:** an HTML legend above the canvas: a solid ember swatch "November", and a dashed ink-soft swatch "October" (made with a `border-t-2 border-dashed border-ink-soft` span). Only "November" + the note "No data for October to compare." when `not prev_has_data`. Canvas `chart-cumulative`. Table: Day / Nov so far / Oct so far (blank past each month's end).
    - **Six-month card:** a local `{% macro six_month_card() %}` (reused in the empty branch). Canvas `chart-six`. Note "More months will appear here as you keep tracking." when `six_months|length == 1`. Table: Month (link) / Total.
- `{% else %}`: `card mt-6 text-center`: "No expenses in {month_label}." (or "We couldn't load your numbers." when `load_failed`) + `button("Go to dashboard", url_for('expenses.dashboard', month=view.month_value), "dark", extra="mt-4")`. Then `six_month_card()` if `view.show_six_months` (inside `mt-6 lg:max-w-[calc(50%-0.75rem)]` so it keeps its desktop width).
- `<script type="application/json" id="analytics-data">{{ chart_data|tojson }}</script>`. `tojson` escapes `<`, `>`, `&`, `'`, so user category names are safe.

**`{% block scripts %}`** (only when `view.has_expenses or view.show_six_months` for Chart.js; `dashboard.js` always):
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.6.1/chart.umd.min.js"
        integrity="sha512-vMRyUfXe50uUhhDC+fk6UYBA/1VPj+I7Jn+wK0A3+wSVeUgT9OCz/xoF2M8KFvrmUOlb4Anv0FQUw8NafuzYPw=="
        crossorigin="anonymous" referrerpolicy="no-referrer" defer></script>
<script src="{{ url_for('static', filename='js/analytics.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/dashboard.js') }}" defer></script>
```
Deferred scripts run in order, so `Chart` exists before `analytics.js` runs. `base.html` is untouched, so Chart.js loads on `/analytics` only.

### 3.13 `public/static/js/analytics.js` (new)
ES5 style like `dashboard.js`, an IIFE, `"use strict"`, no inline JS anywhere (§4).

### 3.14 Build + docs
- `.\tailwindcss.exe -i app/styles/input.css -o public/static/css/output.css --minify`, then commit `output.css`.
- **README.md:** routes table (`/analytics` → `routes/analytics.py`), the file tree (remove placeholders/coming_soon, add analytics files), a "Database functions" entry for `get_month_analytics` (args, invoker, money-as-text), and a **"Chart.js (CDN pin)"** section: version 4.6.1, URL, SRI, and how to bump it (the cdnjs API `?fields=sri` + the PowerShell hash check in §4.1).
- **CLAUDE.md:** roadmap 04 → Done + "Spec 04 delivered" line. Architecture: the routes list (analytics instead of placeholders), templates (remove coming_soon), the Placeholders bullet replaced with an **Analytics** bullet (the RPC, JSON script tag, Chart.js pinned on that page only).

### 3.15 Commits (small, focused)
1. `docs(plan): spec 04 analytics plan` (the plan + `specs/04-analytics-spec.md`, which is untracked)
2. `feat(db): get_month_analytics RPC for the analytics page`
3. `refactor(dashboard): shared month picker with prev/next arrows`
4. `feat(analytics): analytics page, stats and data tables`
5. `feat(analytics): Chart.js charts`
6. `docs: README and CLAUDE.md for spec 04` (+ `output.css` rebuild in whichever commit adds classes)

**Ask Daniyal before `git push`** (pushing deploys to Vercel).

---

## 4. Chart.js setup

### 4.1 Version pin + SRI check (step 0)
- `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.6.1/chart.umd.min.js`, SRI as in §3.12.
- Verify locally (PowerShell, temp file):
  ```powershell
  $f = Join-Path $env:TEMP "chart-4.6.1.js"
  curl.exe -sSfL "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.6.1/chart.umd.min.js" -o $f
  "sha512-" + [Convert]::ToBase64String([Security.Cryptography.SHA512]::Create().ComputeHash([IO.File]::ReadAllBytes($f)))
  ```
  The output must equal the integrity value exactly. If it differs, stop and recheck the cdnjs API.

### 4.2 Data flow
Flask → `get_month_analytics` (1 RPC) → `AnalyticsView`. Jinja renders the stats, legend, notes and tables. `chart_payload(view)` goes to `<script type="application/json" id="analytics-data">`. `analytics.js` runs `JSON.parse(el.textContent)` and draws only the canvases that exist (`document.getElementById(...)` checks; the empty state has only `chart-six`). If `typeof Chart === "undefined"` (CDN blocked / SRI fail), it unhides `[data-chart-error]` and stops.

### 4.3 Theme + palette
```js
var css = getComputedStyle(document.documentElement);
function token(name, fallback) { return css.getPropertyValue(name).trim() || fallback; }
var INK = token("--color-ink", "#141414"), INK_SOFT = token("--color-ink-soft", "#4A4A4A"),
    EMBER = token("--color-ember", "#D9541E"), GRID = token("--color-cream-dark", "#EAE3D6");
var NEUTRAL = "#BDB3A3";   // non-highlighted bars (warm grey, visible on white cards)
var REST    = "#D9D3C7";   // "Everything else" slice + its legend dots
var PALETTE = [            // 8 muted colours, by_category order; ember is never used here
  "#2F4858",  // deep slate
  "#5B8E7D",  // sage
  "#C9A227",  // ochre
  "#7B6D8D",  // muted plum
  "#4F7CAC",  // dusty blue
  "#B5838D",  // dusty rose
  "#8A9A5B",  // olive
  "#6B4E3D"   // cocoa
];
```
During implementation, load the `dataviz` skill and run its palette validator against white (#FFFFFF card) and cream. Adjacent slices need to be distinguishable (including the common colour-vision deficiencies), and none should read as ember. If the validator flags something, adjust a value and record it in the README.

Defaults: `Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, sans-serif"`, `Chart.defaults.color = INK_SOFT`, `responsive: true`, `maintainAspectRatio: false`. If `matchMedia("(prefers-reduced-motion: reduce)")` matches → `Chart.defaults.animation = false`. Draw after `document.fonts.ready` (when available) so the canvas uses Inter.

Shared y scale: `{ beginAtZero: true, border: { display: false }, grid: { color: GRID }, ticks: { maxTicksLimit: 5, callback: moneyShort } }`. x scale: `grid: { display: false }`.

### 4.4 Money helpers (one place, matching the Jinja `money` filter)
```js
function money(value) {
  var n = Math.round(Number(value) * 100) / 100;
  var paise = Math.round(n * 100) % 100 !== 0;
  return "Rs " + n.toLocaleString("en-US", { minimumFractionDigits: paise ? 2 : 0, maximumFractionDigits: paise ? 2 : 0 });
}
function moneyShort(value) {          // axis ticks: Rs 500, Rs 1k, Rs 1.5k, Rs 12k, Rs 1.2M
  var n = Number(value);
  if (n >= 1e6) return "Rs " + trim(n / 1e6) + "M";
  if (n >= 1000) return "Rs " + trim(n / 1000) + "k";
  return "Rs " + n;
  function trim(x) { return (Math.round(x * 10) / 10).toString(); }
}
```
`en-US` grouping (1,234,567) is the same as Python's `f"{:,}"`.

### 4.5 "Everything else" grouping (donut only)
```js
var cats = data.categories, top = cats.slice(0, 6), rest = cats.slice(6);
var labels = top.map(c => c.name), values = top.map(c => Number(c.total)),
    colors = top.map((c, i) => PALETTE[i]), pcts = top.map(c => c.pct);
if (rest.length) {                                   // > 6 categories
  var sum = rest.reduce((s, c) => s + Number(c.total), 0);
  labels.push("Everything else"); values.push(sum); colors.push(REST);
  pcts.push(Math.round(sum / Number(data.total) * 100));
}
// legend dots: index < 6 -> PALETTE[index]; index >= 6 -> REST  (D9)
document.querySelectorAll("[data-legend-index]").forEach(dot => { var i = +dot.dataset.legendIndex; dot.style.backgroundColor = i < 6 ? PALETTE[i] : REST; });
```
The code is written ES5-style in the file; arrows here are for brevity. Donut options: `cutout: "68%"`, `borderColor: "#FFFFFF"`, `borderWidth: 2`, `plugins.legend.display: false`, and a tooltip label of `labels[i] + " · " + money(values[i]) + " · " + pctText(pcts[i])` (`pctText` gives "<1%" for 0 when the value is > 0). The legend list (all categories, HTML) comes from Jinja.

### 4.6 Click / tap handling (daily + 6-month bars)
```js
var noHover = window.matchMedia("(hover: none)");
function followOnClick(urlAt) {
  var armed = null;                                   // index whose tooltip a first tap opened
  return function (event, elements) {
    if (!elements.length) { armed = null; return; }
    var i = elements[0].index, url = urlAt(i);
    if (!url) return;
    var touch = (event.native && event.native.pointerType === "touch") || noHover.matches;
    if (touch && armed !== i) { armed = i; return; }  // 1st tap: touchstart already showed the tooltip
    window.location.href = url;                       // mouse click, or 2nd tap on the same bar
  };
}
function pointer(event, elements, chart) { chart.canvas.style.cursor = elements.length ? "pointer" : "default"; }
```
- Daily: `interaction: { mode: "index", intersect: false }` makes the whole day column the tap target, so the thin bars are easy to tap at 375px. `onClick: followOnClick(i => data.daily[i].url)`, `onHover: pointer`. Bars: `backgroundColor = i === data.biggest_day_index ? EMBER : NEUTRAL`, `borderRadius: 4`, `maxBarThickness: 28`. Tooltip: `displayColors: false`, title `data.daily[i].label`, label `money(raw)`. x ticks: `autoSkip: false`, `maxRotation: 0`, and the callback `function (v, i) { var d = i + 1; return this.chart.width < 480 && d !== 1 && d % 5 ? "" : d; }`. It is re-evaluated on resize.
- Six months: `onClick: followOnClick(i => data.six_months[i].selected ? null : data.six_months[i].url)`. Selected bar `EMBER`, others `NEUTRAL`, `maxBarThickness: 48`. Tooltip title `title`, label `money`.
- **Scrolling isn't blocked:** Chart.js registers its touch listeners as passive and doesn't set `touch-action`. We add no `touch-action: none` and no `preventDefault`. Verified on a touch device in §8.

### 4.7 Cumulative line
- Labels are `1..max(data.days_in_month, data.prev_daily.length)` (add `days_in_month` to the payload). The x-axis then covers the longer of the two months, even when the current month's line stops at today.
- The current dataset uses `daily[].running`, padded with `null`: `borderColor: EMBER`, `borderWidth: 2.5`, `pointRadius: 0`, `pointHoverRadius: 4`, `cubicInterpolationMode: "monotone"`, `spanGaps: false`.
- The prev dataset (only if `has_prev`) uses `prev_daily[].running`: `borderColor: INK_SOFT`, `borderDash: [6, 4]`, `borderWidth: 2`, `pointRadius: 0`.
- `interaction: { mode: "index", intersect: false }`. Tooltip title "Day N", lines `month_short + " " + money(v)`, `filter: item => item.raw != null` (D7). No `onClick`.

---

## 5. Responsive layout

### 5.1 Breakpoints summary
| | Phone < 640 | Tablet 640–1023 | Desktop ≥ 1024 |
|---|---|---|---|
| Page | `container-page` (px-5, max 1200px) | px-8 | px-8 |
| Header | 3 rows | 3 rows (wider) | 1 row |
| Stats | `grid-cols-2 gap-3` | 2×2 until 767, `md:grid-cols-4` from 768 (D5), `sm:gap-4` | 4 in a row, `lg:gap-6` |
| Charts | `grid-cols-1 gap-4` | 1 column | `lg:grid-cols-2 lg:gap-6` (grid stretch → equal heights per row) |
| Chart height | `h-56` (224px) | `sm:h-60` (240px) | `lg:h-[280px]` |
| Donut | 180px, centered, legend below | `sm:flex-row`: donut left, legend right | 200px + legend |

### 5.2 Header markup
```html
<header class="flex flex-wrap items-center gap-x-3 gap-y-3">
  <a href="{{ url_for('expenses.dashboard', month=view.month_value) }}" class="btn-ghost btn-sm order-1 -ml-3 sm:-ml-4">{{ icon("arrow-left","h-4 w-4") }}Dashboard</a>
  <div class="order-2 ml-auto lg:order-4 lg:ml-0">{% include "components/profile_menu.html" %}</div>
  <h1 class="order-3 w-full text-3xl font-extrabold tracking-tight sm:text-4xl lg:order-2 lg:mr-auto lg:w-auto lg:text-5xl">Your {{ accent("spending.") }}</h1>
  {{ month_picker(url_for('analytics.index'), view.month_options, view.month_value, prev_url, next_url, extra="order-4 lg:order-3") }}
</header>
```
On phones: row 1 is ← Dashboard + avatar (`ml-auto`), row 2 is the full-width h1, row 3 is the full-width picker with 44×44 `month-arrow`s and the select `flex-1`. On desktop, the `order` utilities put it in one row: back, heading (`mr-auto`), picker, avatar. The profile menu is included once, so there are no duplicate `<details>`. Its panel is `absolute right-0`, and it stays inside the viewport because the avatar is at the right edge in both layouts.

### 5.3 No horizontal scroll at 375px
- Every grid/flex child has `min-w-0` (`chart-card`, stat cards, legend name column `minmax(0,1fr)` + `truncate`).
- Canvases sit only inside `relative w-full` wrappers. Chart.js sizes to the wrapper, and the canvas is never styled.
- Stat values are `whitespace-nowrap`, and their size is capped by `cqw` of the card's own width. Math at 375: content 335px → card 161px → inner 121px. "Rs 1,234,567" ≈ 6.6em at `13.5cqw` (16.3px) ≈ 108px fits. "Rs 6,450" at `20cqw` → 24px. Python picks the tier by string length (`stat_size`).
- Sub-texts are `truncate`. Tables are `w-full` inside `overflow-y-auto` containers with short columns, and long category names wrap (`break-words`) in tables.
- The select is `min-w-0 max-w-full` (`select-pill`) inside a `flex-1` form.
- Verify with `document.documentElement.scrollWidth <= window.innerWidth` at 375/768/1280 (§8.3).

---

## 6. Edge cases

| Case | Behaviour |
|---|---|
| Empty month (count = 0) | Header + picker. One card "No expenses in November 2026." + **Go to dashboard** (`/dashboard?month=`). The 6-month card shows if any month in `six_months` > 0. Chart.js loads only then |
| Current month, day 1, nothing spent | `days_elapsed = 1`, count 0 → same empty state |
| Current month, day 1, with spending | One daily bar (ember). Daily avg = total. Comparison window "vs 1 Oct" |
| First available month | ‹ disabled (`prev_month` None). `prev.has_data` false → "—" / "No data for October". Chart 3 has one line + "No data for October to compare." |
| Month with no previous data (not the first month, e.g. a gap) | Same as above: `has_data` = the previous month has ≥ 1 expense |
| Prev has data but the window total is 0 | "—" / "Nothing spent 1–22 Oct" (D10). Chart 3 still shows both lines |
| Window capped (31 Mar vs 28 Feb) | `window_end = 28 Feb` → "vs 1–28 Feb" |
| Invalid `?month=` (bad format, `2026-13`, future) | `parse_month_param` → None → current month |
| `?month=` before the first month | SQL clamps to the current month (D3). The page shows the current month |
| > 6 categories | Donut: top 6 + "Everything else" (grey). Legend + table: every category, sorted by total desc, then name |
| 1 category | Full ring, one legend row |
| Only 1 month available | The 6-month chart shows 1 bar + "More months will appear here as you keep tracking." |
| Six months crossing a year | "Aug … Dec, Jan '27" |
| Tiny category share | "<1%" |
| DB unreachable | Flash the friendly message, `empty_view` ("We couldn't load your numbers."), no crash |
| Image icon categories | `storage.icon_url()` → `category_icon(size="sm")` in the legend and the Biggest card |

---

## 7. Accessibility & no-JS

### 7.1 Aria summaries (built in `services/analytics.py`)
- Donut: "Food was your top category at 42% of Rs 6,450. 9 categories in total."
- Daily: "Daily spending for November 2026, 22 days. Your biggest day was Sat, 21 Nov at Rs 1,450."
- Cumulative: "By day 22 you had spent Rs 6,450 in November, compared with Rs 5,760 by day 22 of October." (Without previous data: "By day 22 you had spent Rs 6,450 in November. No data for October to compare.")
- Six months: "Monthly totals from June to November 2026. November 2026: Rs 6,450. Highest: October 2026 at Rs 8,100."

Each goes on `<canvas role="img" aria-label="…">`, and each card has an `<h2>` linked via `aria-labelledby`.

### 7.2 Data tables
Each chart card has `<details><summary>Show data</summary>` with a `<table>` that has an sr-only `<caption>` and `<th scope="col">`:
- Category / Amount / Share
- Day / Amount, where the day is a link to the dashboard day, so keyboard and no-JS users can do what clicking a bar does
- Day / {Nov} so far / {Oct} so far
- Month / Total, where the month is a link to `/analytics?month=`

All values are formatted by the Jinja `money` / `short_date` filters.

### 7.3 No-JS
The stats, legend list, notes and tables are all server-rendered. `<noscript><p class="chart-note">Turn on JavaScript to see the charts.</p></noscript>` sits above the charts grid. The month dropdown has its noscript "Go" button, and the arrows are plain links. Only the canvases stay empty.

### 7.4 Never colour alone
▲/▼ + words on the comparison card. Solid vs dashed line + HTML legend labels in chart 3. Ember highlights always have matching text ("Biggest day: …", the bold selected month in the dropdown/table).

### 7.5 Arrows
`aria-label="Previous month"` / `"Next month"`. When disabled they are `<span role="link" aria-disabled="true">`, not links, so they can't be focused or clicked. They are styled faded (`text-ink-soft/30`, `cursor-not-allowed`). Focus rings come from the global `:focus-visible`.

---

## 8. Test plan

### 8.1 Seed data (as `postgres` through `execute_sql`, explicit `user_id`)
1. Ask Daniyal which 2 existing accounts to use (A, B). Read their ids: `select id, created_at from auth.users where email in (...)`.
2. Account A: add 2 custom categories (e.g. "Snacks" 🍿, "Gifts" 🎁), so A has 9 categories (7 defaults + 2). Record their ids so they can be removed later.
3. Account A expenses, all with `note = '[seed-04] …'`:
   - **Jul 2026**: ~8 rows
   - **Aug 2026**: none (a zero month in `six_months`)
   - **Sep 2026**: ~10 rows over 6 categories
   - **Oct 2026** (31 days): ~15 rows over all 9 categories, including two expenses with the **same top amount** on different days (tie-break check) and spending after the 22nd (the window-vs-full difference shows)
   - **Nov 2026** (1–22): ~12 rows over 8 categories, one clearly biggest day
   - Also one small row in a category to get a "<1%" share
4. Account B: ~4 rows in Oct/Nov with distinct amounts.
5. Run §2.4, then the browser checks. **Cleanup** (`delete from public.expenses where note like '[seed-04]%'` + the 2 categories) **only after Daniyal approves.**

Account A's first month = min(earliest expense, signup month). Use whatever month that is to test the first-month state. If A signed up before Jul 2026, also check one empty month before July (empty state + 6-month card).

### 8.2 App run
Run `flask run --debug` with the Tailwind watch. Browser checks use Claude in Chrome (load the `claude-in-chrome` skill) on `http://127.0.0.1:5000`, with Daniyal logging in as A in that browser. If the window can't be resized down to 375px, Daniyal checks 375 in Chrome DevTools device mode (iPhone SE) and a real phone, guided by the checklist below.

### 8.3 Checks per width
- **375px:** the header wraps to 3 rows. The arrows are 44×44. Stats are 2×2 and "Rs 1,234,567" fits (temporarily test a long value by viewing a month with a big seeded total, or by checking the `stat-value-sm` math in DevTools). Charts are stacked in the order donut → daily → cumulative → six, with the donut centered and the legend below. The daily x labels show 1, 5, 10, 15, 20. `scrollWidth <= innerWidth`. Tap a bar: the tooltip shows, a second tap navigates, and swiping over a chart scrolls the page.
- **768px:** 1 chart column, stats 4 in a row with no overflow, donut + legend side by side, `scrollWidth` check.
- **1280px:** header in 1 row, stats ×4, charts 2×2 with equal heights in each row, cursor pointer on bars, `scrollWidth` check.
- Resize 1280 → 375 → 1280 and rotate the phone: the charts redraw at the new size and don't stretch.

### 8.4 Acceptance criteria (spec §12) → how each is verified
| Criterion | Verification |
|---|---|
| Migration exists + applied | File in `supabase/migrations/`; `mcp__supabase__list_migrations` shows `20261122_03_analytics_function` |
| Runs as the caller; A never sees B | §2.3a `prosecdef = false`; §2.4 two-account test both ways |
| anon can't execute | §2.3b `has_function_privilege` false + §2.3c permission denied |
| Totals / daily / categories / 6 months match manual SQL | §2.4 comparison for Oct (past) and Nov (current) |
| Opens on the current month (Karachi) | `/analytics` with no params → "November 2026", daily stops at 22 |
| Dropdown + arrows switch; › disabled on current, ‹ on first | Click through; inspect for `aria-disabled` spans; also on the dashboard |
| Invalid `?month=` → current | Try `?month=abc`, `2026-13`, `2030-01`, a month before the first one |
| Dashboard Analytics keeps the month; ← Dashboard returns to it | Dashboard at Oct → Analytics → URL `?month=2026-10` → ← Dashboard → Oct |
| 4 stat cards correct; current month compares the same days | Compare with the SQL from §2.4 (window sum 1–22 Oct) |
| Donut/legend match; > 6 → "Everything else" in the donut only | A's Oct (9 categories): 7 slices, 9 legend rows, tooltip on the grey slice |
| Daily bars stop at today; biggest highlighted; tap opens the dashboard day | Nov: 22 bars, ember bar = max day; click → `/dashboard?month=2026-11&day=…` shows that day |
| Cumulative: both lines, or one + note | Oct (both); A's first month (one + note) |
| Six months ends at selected, highlighted, click switches | View Oct: bars up to Oct, Oct ember, click Sep → `?month=2026-09` |
| Empty + first-month states | An empty month, and A's first month |
| 375 / 768 / ≥1024 layouts, resize, tap/scroll | §8.3 |
| Chart.js pinned + SRI, only on `/analytics` | View source of `/analytics` vs `/dashboard`; §4.1 hash check; DevTools shows no SRI error |
| No inline JS; data from the JSON tag | `grep -n "<script>" app/templates` returns only `src=` / `type="application/json"` tags; no `on*=` attributes |
| aria-label + Show data per chart; usable without JS | Inspect canvases; disable JS in DevTools → stats, legend, tables, noscript note |
| Works on Vercel | After Daniyal OKs the push: open the Vercel URL, repeat a quick 375/1280 pass, check Chart.js loads (no CSP/SRI errors) |

---

## 9. Risks & conflicts with the current code

1. **Spec vs code: "matches the dashboard's behaviour".** The dashboard doesn't reject months before the first month; it widens the dropdown. Analytics falls back as the spec asks, and the dashboard is unchanged (D12).
2. **Spec file tree says `app/static/js/analytics.js`.** CLAUDE.md forbids `app/static/`, so it goes in `public/static/js/` (D6).
3. **The spec's JSON shape shows money as numbers.** That would be a float in Python, so it is returned as text (D1).
4. **"Compute running totals in JS" vs the no-JS table and "Flask does no adding".** Running totals come from SQL (D2).
5. **Tap behaviour:** a tap fires `touchstart` (tooltip) and then `click`. The "armed index" logic handles it. `pointerType` is missing on some older browsers' click events, and `(hover: none)` is the fallback. Hybrid laptops with touch screens use mouse rules unless the click comes from touch. Test on a real phone.
6. **CDN dependency:** if cdnjs is blocked, the charts don't render. The page stays usable (tables), and a message is shown. An SRI mismatch behaves the same, so the hash check matters.
7. **Tailwind scanning:** JS-only classes wouldn't be generated, so JS sets only inline colour/cursor styles at runtime (allowed: the "no inline `style=""`" rule is about templates). `cqw` arbitrary values need Safari 16+ / Chrome 105+. Older browsers fall back to `vw`-like sizing, which is still small enough not to overflow.
8. **Default function privileges on Supabase** grant `anon` execute. This is handled by the explicit revoke and verified in §2.3.
9. **Viewport testing at 375px** may not be possible by resizing a desktop Chrome window. DevTools device mode or a real phone is the fallback (§8.2).
10. **Seeding real accounts:** the rows are tagged, and cleanup needs approval. Categories added for testing must be removed separately: deleting a category with expenses fails (FK), so delete the expenses first.
11. **Fonts on canvas:** if Inter hasn't loaded, the chart text falls back to system-ui. We wait for `document.fonts.ready`.
12. **Ember text contrast:** ember (#D9541E) on white is ~3.9:1, below AA for small text. The "up" percentage uses `text-ember-dark` (#B84415, ~5.3:1). Ember is kept for chart marks only.
