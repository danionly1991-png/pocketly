# Spec 03 — Dashboard, Add Expense, Expense Detail & Categories

**Project:** Pocketly — a personal expense tracker for managing monthly pocket money
**Spec status:** Ready for planning
**Date:** 2026-11-22
**Depends on:** Spec 01 (Base & Landing), Spec 02 (Auth)
**Next spec:** 04 — Analytics (to be written)

---

## 1. Purpose

Replace the dashboard placeholder with the real Pocketly home screen. A logged-in user can see their expenses for the current month (or any past month or a single day), see how much they have spent this month so far, add an expense, open an expense to view, edit or delete it, and manage their own categories with custom icons.

## 2. Goals

1. **Dashboard:** a list of expenses for the current month by default, plus a top bar with:
   - a **Month** selector (view any past month)
   - a **Date** picker (view a single day of the selected month)
   - an **Analytics** button that opens a coming-soon page
   - a **"Spent this month"** total tab
   - a round **profile / logout** button
2. **Add expense:** a floating "+" button that opens an add-expense panel (amount, category, date, note).
3. **Expense detail:** clicking an expense row opens a detail view with **Edit expense** and **Delete expense**.
4. **Categories:** default categories for every user, plus user-created categories. Every category has an icon that the user can change, either to another emoji or to an uploaded photo from their gallery.

## 3. Out of scope (later specs)

- Analytics, charts and reports (Spec 04). In this spec, Analytics is only a coming-soon page.
- Monthly budget, spending limits and alerts (dropped for now)
- Search, sorting options, export (CSV/PDF), recurring expenses, multiple currencies
- Profile or settings page

---

## 4. Supabase: Claude Code makes the changes

Claude Code already has access to the Pocketly Supabase project (connected in an earlier session). **Claude Code creates and applies all database and storage changes in this spec itself.** Daniyal won't run SQL by hand.

- Write every change as a SQL migration file in `supabase/migrations/` (e.g. `20261122_01_categories_expenses.sql`), commit it, **and** apply it to the Supabase project through Claude Code's Supabase access.
- Create the Storage bucket and its policies the same way (as SQL in a migration where possible).
- After applying, check:
  - that the tables, policies, trigger and bucket exist
  - that RLS is enabled on every new table (run Supabase's security/performance advisors if available)
  - that the defaults were seeded for existing users
- **Ask Daniyal before** running anything destructive (dropping or truncating tables, deleting data or users), and before changing auth settings.
- Never put the `service_role` key in the Flask app or in the repo. The app only uses the anon key plus the logged-in user's access token.

---

## 5. Database changes

### 5.1 Table `categories`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | `default gen_random_uuid()` |
| `user_id` | uuid, not null | FK → `auth.users(id)` `on delete cascade` |
| `name` | text, not null | 1–30 characters, trimmed |
| `icon_type` | text, not null | check in (`'emoji'`, `'image'`) |
| `icon_value` | text, not null | An emoji character, or the Storage object path for an image |
| `is_default` | boolean, not null | default `false`. `true` for seeded categories |
| `created_at` | timestamptz | default `now()` |
| `updated_at` | timestamptz | default `now()`, updated by a trigger |

- Unique per user, case-insensitive: unique index on `(user_id, lower(name))`.
- Index on `user_id`.

### 5.2 Table `expenses`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | `default gen_random_uuid()` |
| `user_id` | uuid, not null | FK → `auth.users(id)` `on delete cascade` |
| `category_id` | uuid, not null | FK → `categories(id)` `on delete restrict` |
| `amount` | numeric(12,2), not null | check `amount > 0` |
| `spent_on` | date, not null | The day the money was spent (Pakistan time) |
| `note` | text, null | Max 500 characters |
| `created_at` | timestamptz | default `now()`. Tie-breaker for ordering within a day |
| `updated_at` | timestamptz | default `now()`, updated by a trigger |

- Index on `(user_id, spent_on desc, created_at desc)`.

### 5.3 Row Level Security

Enable RLS on both tables. For each table, add `select`, `insert`, `update` and `delete` policies limited to `auth.uid() = user_id`. Also:
- On `expenses` insert and update, `category_id` must belong to the same user. Enforce this in the policy's `with check` using an `exists` subquery on `categories`.

### 5.4 Default categories (seeding)

Every user gets these 7 default categories:

| Name | Icon |
|---|---|
| Food | 🍔 |
| Transport | 🚌 |
| Mobile top-up | 📱 |
| Shopping | 🛍️ |
| Education | 📚 |
| Entertainment | 🎬 |
| Other | 📦 |

- A `security definer` function plus a trigger **after insert on `auth.users`** seeds them for new users.
- The migration also seeds them **for users who already exist**. The insert must be idempotent: skip names the user already has.
- Default categories: the user **can change the icon and rename them**. "Other" can't be deleted. Other defaults can be deleted like custom ones (see 7.5).

### 5.5 `updated_at` trigger

One shared `set_updated_at()` trigger function, used by both tables.

### 5.6 Storage: category icons

- Bucket: `category-icons`, **public read** (icons aren't sensitive, and public URLs avoid signing every image on each page load).
- Object path: `{user_id}/{uuid}.webp`. Random names, never the original filename.
- Storage policies on `storage.objects` for this bucket:
  - Insert, update and delete are allowed only when the first folder of the path equals `auth.uid()::text`.
- Upload rules (checked in Flask before uploading):
  - JPG, PNG or WEBP only, max **2 MB**
  - Resize and center-crop to **128×128** and convert to WEBP using **Pillow**
- When a category's image icon is replaced or the category is deleted, delete the old file from Storage.

---

## 6. Routes

All routes below are `login_required` (from Spec 02). Put them in a new blueprint, `app/routes/expenses.py`, with categories in `app/routes/categories.py`. Move `/dashboard` out of `auth.py` into the expenses blueprint. Make `/analytics` login-required as well.

| Route | Method | What it does |
|---|---|---|
| `/dashboard` | GET | Expense list. Query params: `month=YYYY-MM` (default: current month), `day=YYYY-MM-DD` (optional, must be inside `month`) |
| `/expenses` | POST | Create an expense, then redirect back to the dashboard (same month/day view) with "Expense added." |
| `/expenses/<id>` | GET | Expense detail view |
| `/expenses/<id>/edit` | GET, POST | Edit form (pre-filled), then redirect to the detail view with "Expense updated." |
| `/expenses/<id>/delete` | POST | Delete, then redirect to the dashboard with "Expense deleted." |
| `/categories` | GET | Manage categories (list, add, change icon, rename, delete) |
| `/categories` | POST | Create a category (name + emoji or uploaded image) |
| `/categories/<id>` | POST | Update name and/or icon |
| `/categories/<id>/delete` | POST | Delete a category (rules in 7.5) |
| `/analytics` | GET | Coming-soon page, with "← Back to dashboard" |

- An unknown or another user's `<id>` returns the styled 404. RLS returns no row, so this happens naturally.
- Invalid `month` or `day` params (bad format, a future month, a day outside the month) fall back to the default view without crashing.
- Every POST form has a CSRF token. Delete is POST only.

---

## 7. Features & behaviour

### 7.1 Dashboard

**Default view:** all expenses of the **current month** (Asia/Karachi time), newest first (`spent_on desc, created_at desc`).

**Top bar (left → right on desktop):**

| Item | Behaviour |
|---|---|
| **Month** selector | Dropdown of months, from the month of the user's first expense (or their signup month) up to the current month. No future months. Changing it reloads with `?month=` and clears `day`. Label, e.g. "November 2026 ▾" |
| **Date** picker | Combines the old "date" and "day" items. Native `<input type="date">` limited to the selected month (`min` = 1st, `max` = last day or today for the current month). Picking a day shows only that day's expenses. Shows "All days" when no day is picked, and an "×" / "All days" button clears it |
| **Analytics** | Ghost button → `/analytics` (coming soon) |
| **Spent this month** tab | Top-right. See 7.2 |
| **Profile circle** | Round button with the user's initial. Clicking it opens a small menu with the name, email and a **Log out** button (POST, from Spec 02) |

Month and day changes can submit a small GET form automatically (a few lines of vanilla JS). The page must still work if JS is off (show a small "Go" button inside `<noscript>`).

**Expense list:** each expense is one full-width clickable bar (a `card`), and the whole bar links to `/expenses/<id>`.

| No. | Category | Amount | Date / day |
|---|---|---|---|
| 1, 2, 3… (position in the current list) | Icon + name | **Rs 1,250** | "Sat, 21 Nov" |

- On mobile, the bar stacks into two lines: icon + category + amount on the first line, date and No. smaller on the second.
- Note text is not shown in the list (it's only in the detail view).
- **Empty states:**
  - Current month, no expenses: "No expenses yet this month. Tap + to add your first one."
  - Selected day, no expenses: "Nothing spent on {date}."
- When a day is selected, show a small line above the list: "Showing {Sat, 21 Nov} · Rs X that day".
- **Floating "+" button:** fixed at the bottom-right of the screen (`btn-primary`, round, ember), opens the Add Expense panel.

### 7.2 "Spent this month" tab

- A small `card-dark` tab in the top-right of the top bar, next to the profile circle. On mobile it becomes a full-width strip under the top bar.
- Shows:
  - label "Spent in {November}"
  - the big amount, e.g. **Rs 6,450**
  - small text "till {22 Nov}"
- It always shows the **current month's total from day 1 up to today**, whatever month or day is being viewed, because it's the user's running total.
- When a past month is selected, add a secondary line under the list header: "Total for {October 2026}: Rs X".
- Compute totals with a database `sum()` query, not by adding values in Python from paged rows.

### 7.3 Add expense panel

- Opens over the dashboard as a panel anchored to the **bottom-right** (as in the sketch), about 480px wide on desktop. On mobile it is a **bottom sheet** (full width). Use the native `<dialog>` element plus a little vanilla JS, with a dimmed backdrop. Close with ×, Esc or a backdrop click.
- Fields:
  - **Amount:** number, required, "Rs" prefix shown in the input
  - **Category:** a grid or list of category chips with icons. One must be chosen. The last chip, "+ New category", opens `/categories` (or an inline mini-form, if simple)
  - **Date / day:** date input, default **today**, can't be in the future. Under the field, show the day name for the chosen date, e.g. "Saturday"
  - **Note:** textarea, optional, max 500 characters, with a character counter
- Buttons: **Save expense** (`btn-primary`, full width) and Cancel (ghost).
- The form posts to `/expenses`. **On a validation error**, re-render the dashboard with the panel **already open**, entered values kept and errors under the fields.
- On success: redirect to the dashboard view the user was on, with a flash message. If the new expense's date is in a different month than the one being viewed, redirect to that expense's month.

### 7.4 Expense detail (clicking an expense bar)

A page at `/expenses/<id>` that follows the sketch: a large white `card` centered on the cream background.

- **Left column:**
  - **Amount:** big and bold, e.g. "Rs 1,250"
  - **Category:** icon + name
  - **Date / day:** e.g. "Saturday, 21 November 2026"
- **Right column (top):** **Edit expense** (`btn-dark`) and **Delete expense** (ghost, ember text).
- **Note:** a wide box below the details, showing the full note or "No note added." in `ink-soft`.
- "← Back to dashboard" goes back to the month the expense is in.
- **Edit** goes to `/expenses/<id>/edit`: the same fields and layout as the add form, pre-filled, as its own page.
- **Delete** opens a small confirm `<dialog>` ("Delete this expense? This can't be undone.", with Cancel and Delete buttons). Delete POSTs to `/expenses/<id>/delete`.
- On mobile, the columns stack and the buttons go full width under the details.

### 7.5 Categories (`/categories`)

Linked from the "+ New category" chip and from the profile menu ("Manage categories").

- **List:** every category with its icon, name and a "Default" badge where it applies, plus Edit and Delete actions.
- **Add / Edit form:**
  - **Name:** required, 1–30 characters, unique for the user (case-insensitive)
  - **Icon:** pick one of two options:
    1. **Emoji:** choose from a preset grid of about 30 common emojis (food, transport, bills, health, gifts and similar)
    2. **Upload photo:** a file input with `accept="image/*"` (on phones this opens the gallery or camera), plus a small preview before saving. Rules in 5.6
- **Delete:**
  - "Other" can't be deleted (no Delete button).
  - Deleting a category that has expenses asks for confirmation ("{n} expenses will move to Other."). On confirm, move those expenses to the user's "Other" category, then delete. Do both in one database function or transaction.
  - Delete the category's uploaded icon file from Storage, if it has one.

### 7.6 Analytics placeholder

`/analytics` uses `coming_soon.html` with the heading "Analytics" and the text "Charts of where your money goes are coming soon.", plus "← Back to dashboard".

---

## 8. Validation rules

| Field | Rules | Error message |
|---|---|---|
| Amount | Required, number > 0, max 9,999,999.99, at most 2 decimal places | "Enter an amount greater than 0." |
| Category | Required, must be one of the user's categories | "Please choose a category." |
| Date | Required, valid date, not after today (Pakistan time) | "Date can't be in the future." |
| Note | Optional, max 500 characters, trimmed | "Note can be up to 500 characters." |
| Category name | Required, 1–30 characters, trimmed, unique per user | "You already have a category with this name." |
| Icon upload | JPG/PNG/WEBP, ≤ 2 MB, a real image (Pillow opens it) | "Upload a JPG, PNG or WEBP image under 2 MB." |

Show any Supabase errors as friendly messages, never a stack trace.

---

## 9. Formatting & time

- **Timezone:** all "today", "current month" and "till date" logic uses **Asia/Karachi** (`zoneinfo`). Never use the server's local time, because Vercel runs in UTC.
- **Money:** written as "Rs" plus thousands separators. Whole numbers have no decimals (e.g. Rs 1,250). Show 2 decimals only when there are paise (e.g. Rs 99.50). Add a Jinja filter named `money`.
- **Dates:** "Sat, 21 Nov" in the list, "Saturday, 21 November 2026" in the detail view. Add Jinja filters for both.

---

## 10. Design

Use the Spec 01 design system: cream background, `ink` text, `ember` only as an accent, Inter + Instrument Serif, `card` and `card-dark`, pill buttons, and the Spec 02 form-field and flash macros.

- **Dashboard heading:** "Your *month.*" (italic serif accent). On the dashboard and other app pages, the global navbar shows only the logo, which links to `/dashboard`. The top bar replaces the Spec 02 logged-in navbar buttons.
- **Expense bars:**
  - white `card`, rounded-2xl, soft shadow
  - slightly lifts on hover and shows a `cream-dark` border
  - easy to tap on mobile (min height about 56px)
- **Category icons:** a 36px round `cream-dark` circle holding the emoji, or the uploaded image cropped to a circle (`object-cover`).
- **"+" button:** 56px round `ember` button with a white "+", `ember-dark` on hover, with a soft shadow.
- Everything is responsive and readable at **375px**: no horizontal scroll, and the top bar wraps onto two rows on mobile.
- Accessibility:
  - dialogs move focus inside when open and return it when closed
  - the profile circle and "+" have `aria-label`s
  - every expense bar is a real link

---

## 11. Files (expected)

```
supabase/
└── migrations/
    ├── 20261122_01_categories_expenses.sql   # tables, indexes, RLS, triggers, seeding
    └── 20261122_02_category_icons_storage.sql # bucket + storage policies
app/
├── forms.py                 # + ExpenseForm, CategoryForm
├── services/
│   ├── expenses.py          # queries: list by month/day, totals, CRUD
│   ├── categories.py        # CRUD, reassign-to-Other delete, seeding check
│   └── storage.py           # icon validation, resize (Pillow), upload/delete
├── utils/
│   └── dates.py             # Karachi "today", month ranges, Jinja filters (money, dates)
├── routes/
│   ├── auth.py              # /dashboard removed from here
│   ├── expenses.py          # /dashboard, /expenses/*
│   ├── categories.py        # /categories/*
│   └── placeholders.py      # /analytics (login_required)
└── templates/
    ├── components/
    │   ├── top_bar.html         # month, date, analytics, total tab, profile menu
    │   ├── expense_row.html
    │   ├── category_icon.html
    │   ├── expense_form.html    # shared by add panel and edit page
    │   └── confirm_dialog.html
    ├── dashboard.html
    ├── expenses/
    │   ├── detail.html
    │   └── edit.html
    └── categories/
        └── index.html
```

Update `requirements.txt` (add `Pillow`; pin versions), `README.md` (migrations, how Claude Code applies them, the Storage bucket) and `output.css` (rebuild after adding new Tailwind classes and commit it).

---

## 12. Acceptance criteria

**Supabase (done by Claude Code)**
- [ ] Migration files exist in `supabase/migrations/` and are applied to the Supabase project.
- [ ] `categories` and `expenses` exist with the columns, checks and indexes from section 5.
- [ ] RLS is on for both tables. User A can't read, edit or delete user B's categories or expenses, and can't attach B's category to an expense. Test this with two accounts.
- [ ] New sign-ups automatically get the 7 default categories, and existing users have them too.
- [ ] The `category-icons` bucket exists, and users can only write inside their own folder.

**Dashboard**
- [ ] `/dashboard` shows the current month's expenses, newest first, each with No., category (icon + name), amount and date/day.
- [ ] The Month selector shows past months up to the current one and switches the list.
- [ ] The Date picker filters to one day of the selected month, and "All days" clears it.
- [ ] The "Spent this month" tab shows the correct current-month total up to today, in Karachi time.
- [ ] Analytics opens the coming-soon page.
- [ ] The profile circle opens a menu with Log out (POST) and Manage categories.
- [ ] Empty states show correctly.

**Add / view / edit / delete**
- [ ] "+" opens the add panel (bottom-right on desktop, bottom sheet on mobile), and a valid expense saves and appears in the list.
- [ ] Validation errors keep the panel open with the entered values and inline errors.
- [ ] Clicking an expense bar opens the detail view with amount, category, date/day, note, Edit and Delete.
- [ ] Edit saves changes. Delete asks for confirmation, then removes the expense.
- [ ] Future dates and amounts ≤ 0 are rejected.

**Categories**
- [ ] Users can create a category with an emoji or an uploaded photo (resized to 128×128 WEBP).
- [ ] Users can change any category's icon (including defaults) and rename it.
- [ ] Deleting a category moves its expenses to "Other", and "Other" can't be deleted.
- [ ] Replaced or deleted image icons are removed from Storage.

**Quality**
- [ ] Every POST has CSRF. All new routes are `login_required`. Other users' IDs return 404.
- [ ] No `service_role` key in the app or repo.
- [ ] All pages are responsive at 375px, and everything works on the Vercel deployment.

---

## 13. Notes for Claude Code (plan mode)

- Produce a plan that lists every file to create or change **and every Supabase change**, in order, before writing code. Save the plan in the repo's technical plan folder.
- Apply the Supabase changes **first** (migrations → verify → advisors), then build the Flask side.
- Check the current `supabase` Python client API for table queries, RPC calls and Storage uploads (`storage.from_(...).upload`, `get_public_url`, `remove`) and adapt if they've changed.
- Use a fresh Supabase client per request with the user's access token set (as in Spec 02), so RLS applies as that user.
- Do the "reassign to Other, then delete" category step in one Postgres function (`rpc`) so it's atomic.
- Keep the expense form one shared component for both the add panel and the edit page.
- Don't build analytics or any budget features in this spec.
