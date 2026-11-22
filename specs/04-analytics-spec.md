# Spec 04 — Analytics

**Project:** Pocketly — a personal expense tracker for managing monthly pocket money
**Spec status:** Ready for planning
**Date:** 2026-11-22
**Depends on:** Spec 01 (Base & Landing), Spec 02 (Auth), Spec 03 (Dashboard, Expenses & Categories)
**Next spec:** 05 — to be decided

---

## 1. Purpose

Replace the `/analytics` coming-soon page with a real analytics page. It shows where the user's money went in one month. The page opens on the **current month**, and the user can switch to any past month. Every part of the layout must work well on both **desktop and mobile phones** (down to 375px wide).

## 2. Goals

1. **Month selection:** the current month by default, a month dropdown (same range as the dashboard), and ‹ › arrows to step one month back or forward.
2. **Stats row:** 4 cards: Total spent · Daily average · Biggest expense · vs last month.
3. **Four charts:**
   1. **Where my money went:** donut chart of spending by category, plus a legend list
   2. **Daily spending:** bar chart for each day of the month. Clicking a bar opens that day on the dashboard
   3. **This month vs last month:** cumulative spending, two lines
   4. **Last 6 months:** bar chart of monthly totals ending at the selected month
4. **Responsive layout** that adapts between phone, tablet and desktop (section 8).

## 3. Out of scope (later specs)

- Top 5 expenses list and spending-by-weekday chart (possible later additions)
- Budgets, spending limits and alerts (dropped)
- Custom date ranges, year view, category drill-down pages
- Export (CSV/PDF), sharing or printing charts

---

## 4. Supabase: Claude Code makes the changes

As in Spec 03, **Claude Code writes and applies all database changes itself.** Daniyal won't run SQL by hand.

- Write the change as a migration file, e.g. `supabase/migrations/20261122_03_analytics_function.sql`. Commit it **and** apply it to the Supabase project.
- After applying it, check that the function exists, that it runs as the calling user (RLS applies), and that it returns correct numbers for a test month. Run the Supabase advisors if they are available.
- **Ask Daniyal before** running anything destructive.
- No new tables in this spec. No `service_role` key in the app or repo.

---

## 5. Database: analytics function

### 5.1 `get_month_analytics(p_month_start date, p_today date) returns jsonb`

- `p_month_start`: the first day of the selected month, e.g. `2026-11-01`
- `p_today`: today's date in **Asia/Karachi**, passed in by Flask (the database's clock is UTC, so don't use `current_date`)
- `security invoker` (the default), so the existing RLS on `expenses` and `categories` limits every row to `auth.uid()`. **Not** `security definer`.
- `grant execute ... to authenticated`. Revoke from `anon` and `public`.
- `stable`. One call returns everything the page needs, so there's one round trip per page load.

### 5.2 Definitions

- **Selected month** = `p_month_start` to the last day of that month.
- **Days counted** (`days_elapsed`):
  - current month: `p_today`'s day of the month (e.g. 22)
  - past month: the number of days in that month
- **Previous month** = the calendar month before the selected one.
- **Comparison window** (for "vs last month"):
  - current month: day 1 to day `days_elapsed` of the previous month (the same number of days, capped at the previous month's last day). This keeps the comparison fair, e.g. 1–22 Nov vs 1–22 Oct.
  - past month: the whole previous month.

### 5.3 Returned JSON shape

```json
{
  "month": "2026-11",
  "is_current_month": true,
  "days_in_month": 30,
  "days_elapsed": 22,
  "total": 6450.00,
  "count": 37,
  "daily_average": 293.18,
  "biggest": { "id": "uuid", "amount": 1250.00, "spent_on": "2026-11-21",
               "category_name": "Food", "icon_type": "emoji", "icon_value": "🍔" },
  "prev": { "month": "2026-10", "has_data": true,
            "window_total": 5760.00, "full_total": 8100.00 },
  "by_category": [
    { "category_id": "uuid", "name": "Food", "icon_type": "emoji", "icon_value": "🍔",
      "total": 2700.00, "count": 15 }
  ],
  "daily": [ { "day": 1, "total": 0 }, { "day": 2, "total": 450.00 } ],
  "prev_daily": [ { "day": 1, "total": 120.00 } ],
  "six_months": [ { "month": "2026-06", "total": 7200.00 } ]
}
```

Rules:
- `daily` has **one entry for every day from 1 to `days_elapsed`**, including zeros (use `generate_series`). Future days are not included.
- `prev_daily` has one entry for every day of the whole previous month, including zeros. Empty if `prev.has_data` is false.
- `by_category` lists only categories with spending in the month, sorted by `total desc`, then `name`.
- `six_months` covers the 6 months ending at the selected month, oldest first, including zero months. Leave out months before the user's first available month (the same lower bound as the dashboard month selector), so a new user may see fewer than 6 bars.
- `biggest` is `null` when the month has no expenses. On a tie, pick the newest one (`spent_on desc, created_at desc`).
- `daily_average` = `total / days_elapsed`, rounded to 2 decimals.
- Every sum is done in SQL. Flask does no adding.

---

## 6. Routes

| Route | Method | What it does |
|---|---|---|
| `/analytics` | GET | Analytics page. Query param `month=YYYY-MM` (default: current month in Karachi time) |

- Move `/analytics` from `placeholders.py` into a new blueprint, `app/routes/analytics.py`. It stays `login_required`.
- An invalid `month` (bad format, a future month, a month before the user's first available month) falls back to the current month without crashing. This matches the dashboard's behaviour.
- **Links between pages:**
  - The dashboard's **Analytics** button links to `/analytics?month=<the month being viewed on the dashboard>`.
  - The analytics page's **← Dashboard** link goes to `/dashboard?month=<selected month>`.

---

## 7. Features & behaviour

### 7.1 Page header

| Item | Behaviour |
|---|---|
| **← Dashboard** | Ghost link back to the dashboard for the selected month |
| **Heading** | "Your *spending.*" (italic serif accent, as on the dashboard) |
| **Month picker** | `‹ November 2026 ▾ ›`. The dropdown has the same options as the dashboard's Month selector. Changing it reloads with `?month=`. **‹** goes to the previous month and is disabled at the first available month. **›** goes to the next month and is disabled at the current month. The arrows are plain links, so they work without JS |
| **Profile circle** | The same profile menu as the dashboard (reuse the component) |

Pull the month dropdown out of `top_bar.html` into a shared `components/month_picker.html`, used by both the dashboard and analytics, so the two stay identical. As on the dashboard, the dropdown submits automatically with a little JS and has a `<noscript>` "Go" button.

### 7.2 Stats row (4 cards)

| Card | Main value | Small text under it |
|---|---|---|
| **Total spent** | Rs 6,450 | "37 expenses" |
| **Daily average** | Rs 293 | "over 22 days" |
| **Biggest expense** | Rs 1,250, with the category icon | "Food · Sat, 21 Nov". The whole card links to `/expenses/<id>` |
| **vs last month** | ▲ 12% or ▼ 8% | Current month: "vs 1–22 Oct (Rs 5,760)". Past month: "vs October (Rs 8,100)" |

- "vs last month" percent = `(total − prev window total) / prev window total × 100`, rounded to a whole number.
  - **Up** (spent more) is shown in `ember` with ▲. **Down** (spent less) is shown in a calm green or `ink` with ▼. The arrow and the words carry the meaning, so colour is never the only signal.
  - If the previous month has no data or its total is 0, the card shows "—" and the text "No data for October".
- The "Total spent" card uses `card-dark`, so it stands out like the "Spent this month" tab. The other three use `card`.

### 7.3 Chart 1: Where my money went (donut)

- A donut of `by_category` totals, with the month total in the middle ("Rs 6,450", plus "total" in small text).
- **Legend list** next to the donut on desktop and under it on mobile. Build it in **HTML**, not with Chart.js's own legend, so it wraps and stays readable. One row per category: colour dot · icon · name · amount · percent, e.g. `● 🍔 Food   Rs 2,700   42%`. Sorted largest first.
- **More than 6 categories:** the donut shows the top 6 slices plus one slice called "Everything else" for the rest. The legend list still shows **every** category. (Don't call this slice "Other", because that's a real category.)
- Tooltip: "Food · Rs 2,700 · 42%".

### 7.4 Chart 2: Daily spending (bars)

- One bar per day from 1 to `days_elapsed` (for the current month, the bars stop at today).
- The x-axis shows day numbers. On mobile, let Chart.js skip labels so only about every 5th day is shown.
- The **biggest day** is drawn in `ember`. All other bars use one neutral colour.
- Tooltip: "Sat, 21 Nov · Rs 1,450".
- **Clicking or tapping a bar** opens `/dashboard?month=YYYY-MM&day=YYYY-MM-DD`, which reuses the day view from Spec 03. Show `cursor: pointer` on hover. On touch screens, the first tap shows the tooltip, and tapping a bar whose tooltip is already open follows the link.
- Under the chart, small text: "Biggest day: Sat, 21 Nov — Rs 1,450".

### 7.5 Chart 3: This month vs last month (cumulative lines)

- Two lines of the running total by day of the month:
  - **Selected month:** solid `ember` line, running from day 1 to `days_elapsed`
  - **Previous month:** dashed neutral line, for the whole previous month
- The x-axis runs from 1 to the longer of the two months.
- Legend: "November" and "October" (simple HTML labels above the chart).
- Tooltip shows both values for that day, e.g. "Day 22 · Nov Rs 6,450 · Oct Rs 5,760".
- If the previous month has no data, show only the selected month's line, with the note "No data for October to compare."
- Compute the running totals in JS from `daily` and `prev_daily` (plain adding of values the database already summed).

### 7.6 Chart 4: Last 6 months (bars)

- One bar per month in `six_months`, labelled "Jun", "Jul" … "Nov". If the months cross a year, add the year to January, e.g. "Jan '27".
- The **selected month's bar** is `ember`, and the others are neutral.
- Tooltip: "October 2026 · Rs 8,100".
- Clicking a bar opens `/analytics?month=` for that month.
- If only one month is available, still show the chart with the note "More months will appear here as you keep tracking."

### 7.7 Empty and edge states

| Situation | What to show |
|---|---|
| Selected month has no expenses | Keep the header and month picker. Replace the stats and charts with one `card`: "No expenses in {November 2026}." plus a **Go to dashboard** button. Still show the 6-month chart if earlier months have data |
| First available month (nothing before it) | "vs last month" card shows "—". Chart 3 shows one line plus the note |
| Current month, day 1 with nothing spent | The same as the empty state |
| Only 1 category used | The donut is a full ring and the legend has one row. Fine as is |

### 7.8 Charting library and data flow

- **Chart.js 4** from a CDN. Check for the latest 4.x version, **pin it** (no `@latest`), add an SRI `integrity` hash plus `crossorigin`, and load it with `defer` **on the analytics page only**.
- Flask calls the RPC once, then:
  - renders the stats cards, legend list, notes and data tables in **Jinja** (server-side, using the `money` and date filters)
  - puts the raw JSON in `<script type="application/json" id="analytics-data">{{ data | tojson }}</script>`
- `static/js/analytics.js` reads that JSON and draws the 4 charts. No inline JS.
- In JS, format money the same way as the Jinja `money` filter: "Rs", thousands separators, decimals only when there are paise. Put this in one small helper.
- **Category colours:** define one palette of **8 muted colours** in `analytics.js` that sit well on the cream background and are easy to tell apart. Assign them in `by_category` order (largest first). "Everything else" uses a light grey. `ember` is **not** part of the category palette. It is only used as the highlight colour (biggest day, selected month, current-month line).
- Chart text uses Inter and the `ink` / `ink-soft` colours. Use light gridlines (`cream-dark`) on the y-axis only, no x gridlines, and y-axis ticks formatted as money ("Rs 1k" style above 1,000 is fine).

---

## 8. Responsive layout (desktop ↔ mobile)

The page is built with a **Tailwind CSS grid** that changes by screen width. Chart.js runs with `responsive: true` and `maintainAspectRatio: false`. Each chart's height comes from its wrapper `div`, never from the canvas, so charts resize smoothly when the screen rotates or the window is resized.

### 8.1 Breakpoints

| Screen | Width | Stats row | Charts |
|---|---|---|---|
| **Phone** | < 640px | 2 × 2 grid | 1 column, stacked |
| **Tablet** | 640–1023px | 4 in a row (or 2 × 2 if the cards get too tight) | 1 column, wider charts |
| **Desktop** | ≥ 1024px | 4 in a row | 2 × 2 grid |

Max content width is about 1200px, centered, with the same page padding as the dashboard.

### 8.2 Desktop (≥ 1024px)

```
┌──────────────────────────────────────────────────────────────┐
│ ← Dashboard        Your *spending.*      ‹ November 2026 ▾ › ●│
├──────────────┬──────────────┬──────────────┬─────────────────┤
│ Total spent  │ Daily avg    │ Biggest      │ vs last month   │
│ Rs 6,450     │ Rs 293       │ Rs 1,250 🍔  │ ▲ 12%           │
├──────────────┴──────────────┴─┬────────────┴─────────────────┤
│ Where my money went           │ Daily spending               │
│  (donut)   ● 🍔 Food     42%  │  ▂▅▁▇▃▂▁▆▂▃▄▁ …              │
│            ● 🚌 Transport 20% │                              │
├───────────────────────────────┼──────────────────────────────┤
│ This month vs last month      │ Last 6 months                │
│  (two cumulative lines)       │  ▃ ▅ ▄ ▆ ▅ ▇                 │
└───────────────────────────────┴──────────────────────────────┘
```

- Header: one row, with "← Dashboard" on the left, the heading in the middle or left, and the month picker plus profile circle on the right.
- Chart cards: `lg:grid-cols-2`, equal heights in each row. Chart area about **280px** tall.
- In the donut card, the donut and the legend list sit side by side (donut about 200px, legend fills the rest).

### 8.3 Phone (< 640px, tested at 375px)

```
┌───────────────────────────┐
│ ← Dashboard             ● │
│ Your *spending.*          │
│ [‹]  November 2026 ▾  [›] │  ← full-width row
├─────────────┬─────────────┤
│ Total spent │ Daily avg   │
│ Rs 6,450    │ Rs 293      │
├─────────────┼─────────────┤
│ Biggest     │ vs last mo. │
│ Rs 1,250 🍔 │ ▲ 12%       │
├─────────────┴─────────────┤
│ Where my money went       │
│        (donut)            │
│ ● 🍔 Food   Rs 2,700  42% │
│ ● 🚌 Transport  …    20%  │
├───────────────────────────┤
│ Daily spending            │
├───────────────────────────┤
│ This month vs last month  │
├───────────────────────────┤
│ Last 6 months             │
└───────────────────────────┘
```

- Header wraps onto 3 rows: (1) "← Dashboard" + profile circle, (2) heading, (3) month picker at full width, with ‹ and › as **44×44px** tap targets on each side of the dropdown.
- Stats: `grid-cols-2`. Values are slightly smaller (e.g. `text-xl` instead of `text-3xl`) so "Rs 1,234,567" still fits on one line. Long values may shrink but never overflow.
- Chart order: donut → daily → vs last month → 6 months.
- Chart area about **220–240px** tall. The donut is centered (about 180px), with the legend list underneath at full width.
- The daily chart keeps all bars (up to 31 bars fit at 375px) but shows fewer x labels.
- **No horizontal scrolling anywhere.** Charts must never be wider than their card.
- Tooltips work on tap. Make sure a tap on a chart doesn't block page scrolling.

### 8.4 Card styling

- Every chart sits in a white `card` (rounded-2xl, soft shadow, the same padding as the expense bars), with a small heading such as "Where my money went" in Inter semibold.
- Spacing between cards: `gap-4` on phones, `gap-6` on desktop.

---

## 9. Accessibility & no-JS

- Each chart card has a real heading (`<h2>`) and the canvas has `role="img"` plus an `aria-label` summary written by Flask, e.g. "Food was your top category at 42% of Rs 6,450."
- Under each chart, add a `<details>` element, "Show data", holding a simple table of the same numbers (category / amount / % · day / amount · month / amount). This is the screen-reader and no-JS fallback, and it's useful on phones too.
- Without JS, the stats, legend list, notes and data tables still show, and only the canvases are empty. Add a `<noscript>` note: "Turn on JavaScript to see the charts."
- Never use colour as the only signal: ▲/▼ arrows plus text for the comparison, and a dashed vs solid line in chart 3.
- The month arrows have `aria-label`s ("Previous month", "Next month"). Disabled arrows use `aria-disabled="true"` and are not links.

---

## 10. Formatting & time

- Everything follows Spec 03 section 9: **Asia/Karachi** for "today" and "current month", "Rs" money formatting, and the "Sat, 21 Nov" date style.
- Flask computes `p_month_start` and `p_today` using `zoneinfo` and passes them to the RPC.

---

## 11. Files (expected)

```
supabase/
└── migrations/
    └── 20261122_03_analytics_function.sql   # get_month_analytics + grants
app/
├── services/
│   └── analytics.py         # calls the RPC, prepares view data (aria summaries, labels)
├── routes/
│   ├── analytics.py         # /analytics (login_required)
│   └── placeholders.py      # /analytics removed from here
├── static/
│   └── js/
│       └── analytics.js     # reads JSON, draws 4 charts, palette, money helper
└── templates/
    ├── components/
    │   ├── month_picker.html    # shared by dashboard + analytics (‹ dropdown ›)
    │   ├── stat_card.html
    │   └── chart_card.html      # heading + canvas wrapper + <details> data table
    ├── analytics.html
    └── dashboard.html           # uses month_picker.html, Analytics link keeps ?month=
```

Also update `top_bar.html` to use `month_picker.html`, plus `README.md` (the analytics function and the Chart.js CDN pin) and `output.css` (rebuild after new Tailwind classes and commit it).

---

## 12. Acceptance criteria

**Supabase (done by Claude Code)**
- [ ] The migration exists in `supabase/migrations/` and is applied.
- [ ] `get_month_analytics` runs as the calling user. User A never sees user B's numbers (test with two accounts).
- [ ] `anon` can't execute the function.
- [ ] For a test month, the totals, daily series (with zeros), category totals and 6-month totals match a manual SQL check.

**Page & month selection**
- [ ] `/analytics` opens on the current month (Karachi time).
- [ ] The dropdown and ‹ › arrows switch months. › is disabled on the current month, and ‹ on the first available month.
- [ ] Invalid `?month=` values fall back to the current month.
- [ ] The dashboard's Analytics button keeps the viewed month, and ← Dashboard goes back to the selected month.

**Stats & charts**
- [ ] The 4 stat cards show correct values. For the current month, "vs last month" compares the same number of days.
- [ ] The donut and legend list match the category totals. More than 6 categories are grouped as "Everything else" in the donut only.
- [ ] Daily bars stop at today for the current month. The biggest day is highlighted, and tapping a bar opens that day on the dashboard.
- [ ] The cumulative chart shows both months, or one line plus a note when there's no previous data.
- [ ] The 6-month chart ends at the selected month, highlights it, and clicking a bar switches to that month.
- [ ] The empty month and first month states show correctly.

**Responsive**
- [ ] At **375px**: the header wraps to 3 rows, stats are 2 × 2, charts are stacked, and there's no horizontal scroll.
- [ ] At **768px**: one chart column. Stats fit without overflowing.
- [ ] At **≥ 1024px**: stats in a row of 4, charts in a 2 × 2 grid with equal heights in each row.
- [ ] Rotating the phone or resizing the window redraws the charts at the new size without stretching.
- [ ] Tapping on charts shows tooltips and doesn't block page scrolling.

**Quality**
- [ ] Chart.js is version-pinned with SRI and loads only on `/analytics`.
- [ ] No inline JS. Data comes from the JSON script tag.
- [ ] Each chart has an aria-label and a "Show data" table. The page is usable without JS (stats + tables).
- [ ] Works on the Vercel deployment.

---

## 13. Notes for Claude Code (plan mode)

- Produce a plan that lists every file to create or change **and the Supabase change**, in order, before writing code. Save it in the repo's technical plan folder.
- Apply and verify the migration **first**, then build the Flask side.
- Seed some test expenses across at least 3 months and 7+ categories (on a test account) to check the charts, the "Everything else" grouping, and the edge states. Ask Daniyal before deleting any test data afterwards.
- Check the current Chart.js 4 docs for responsive options, `onClick` handling and touch tooltips, and adapt if anything has changed.
- Check the layout at 375px, 768px and 1280px in the browser before calling the work done.
- Don't build budgets, export or the optional extras from section 3.
