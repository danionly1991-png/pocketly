# Pocketly

Pocketly is a simple expense tracker for managing your monthly pocket money. You log daily expenses in seconds and see exactly how this month is going.

Stack: Flask + Jinja2, Tailwind CSS v4 (standalone CLI), Supabase (Auth, Postgres, Storage), Pillow for icon uploads, deployed on Vercel.

---

## Project layout

```
app/
  __init__.py          create_app() factory, registers blueprints, CSRF, 404 handler
  config.py            Config class (reads env vars / .env)
  supabase_client.py   get_supabase() (anon, for Auth) and get_user_supabase(token) (acts as the logged-in user, so RLS applies); both per request on flask.g
  auth_utils.py        login_required, logged_out_only, current user, token refresh, safe_next
  forms.py             Flask-WTF forms (auth, ExpenseForm, CategoryForm)
  services/            auth_service.py (Supabase Auth only), expenses.py, categories.py, analytics.py, storage.py (icon upload/resize), db.py (shared errors/client)
  utils/dates.py       Asia/Karachi "today", month/day helpers, Jinja filters (money, dates)
  routes/              main.py (landing), auth.py, expenses.py (/dashboard, /expenses/*), categories.py (/categories/*), analytics.py (/analytics)
  styles/input.css     Tailwind source: theme tokens (@theme) + component classes
  templates/           base.html, landing.html, dashboard.html, analytics.html, 404.html,
                       auth/, expenses/ (detail, edit), categories/, components/
public/static/         served at /static/* (Vercel CDN in production, Flask locally)
  css/output.css       compiled Tailwind CSS (committed)
  js/                  password-toggle, dialogs, dashboard, expense-form, category-form, analytics (small vanilla scripts)
  img/favicon.svg
supabase/migrations/   SQL migrations (applied to the Supabase project)
wsgi.py                entry point for Vercel and `flask run`
vercel.json            Vercel function settings
specs/                 feature specs
technical-plan/        implementation plans
```

---

## Local setup

Requires Python 3.12+ (the project pins 3.14 in `.python-version`).

**Windows (PowerShell)**

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask run --debug
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask run --debug
```

Open http://127.0.0.1:5000. Flask finds the app through `wsgi.py`, so `FLASK_APP` isn't needed.

The app starts even when `.env` is empty, but sign up and login need `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SECRET_KEY` and `SITE_URL` (a missing value logs a warning). See [Supabase Auth setup](#supabase-auth-setup) below.

### Environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs the login session cookie. Required. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SUPABASE_URL` | Supabase project URL (Project settings → API) |
| `SUPABASE_ANON_KEY` | Supabase anon key (the newer "publishable" key also works) |
| `SITE_URL` | Public URL of the app, no trailing slash. Used for the links in verification and reset emails. `http://127.0.0.1:5000` locally, `https://<your-app>.vercel.app` on Vercel |
| `FLASK_ENV` | `development` or `production` (app-level flag) |
| `FLASK_DEBUG` | `1` locally for the debugger and auto-reload (same as `flask run --debug`) |

`.env` is git-ignored. Never commit real keys.

---

## Supabase Auth setup

Login runs on the server in Flask. Do these steps once in the Supabase dashboard (Project → Authentication):

1. **Sign In / Providers → Email:** enabled, with **Confirm email ON**. Optionally set the minimum password length to 8 to match the app's rule.
2. **URL Configuration:**
   - **Site URL:** `https://<your-app>.vercel.app`
   - **Redirect URLs:** add `https://<your-app>.vercel.app/**`, `http://127.0.0.1:5000/**` and `http://localhost:5000/**`
3. **Email Templates:** leave them on Supabase's defaults. Editing them needs a custom SMTP provider, and the app works without that (see "How email links work" below).
4. **Vercel → Environment Variables:** set `SITE_URL=https://<your-app>.vercel.app` next to the other variables, then redeploy.

### How email links work

With Supabase's default templates, the verification and reset links go to Supabase first. Supabase checks the link, then redirects the browser to `SITE_URL/auth/confirm` with the tokens in the URL **fragment**:

```
/auth/confirm#access_token=...&refresh_token=...&expires_in=3600&type=signup      (type=recovery for password reset)
/auth/confirm#error=access_denied&error_code=otp_expired&error_description=...    (expired or used link)
```

A fragment (`#...`) is never sent to the server, so Flask can't read it. The flow is:

1. `/auth/confirm` has no `token_hash` query param, so it renders a small "Verifying..." page.
2. A short inline script reads `window.location.hash` and clears it from the address bar with `history.replaceState` straight away, so the tokens don't stay visible.
3. If the hash holds an error, or no tokens, the script goes to `/auth/link-error` (the styled "link expired" page).
4. Otherwise it POSTs `access_token`, `refresh_token` and `type` as JSON to `/auth/session`, with the CSRF token in an `X-CSRFToken` header.
5. `/auth/session` does not trust the tokens. `auth_service.verify_tokens` calls Supabase `set_session`, which checks the access token with Supabase (and refreshes it if it has expired). Invalid tokens go to the link-error page.
6. On success the server replies with JSON `{"redirect": "..."}` and the script follows it:
   - `type=signup`: the user is logged in, then redirected to `/dashboard` ("Email verified. Welcome to Pocketly!").
   - `type=recovery`: the tokens are kept in `session["recovery"]` (not a login yet), then redirected to `/reset-password`.

Tokens are never logged.

**Optional upgrade (custom SMTP):** once you can edit email templates, set the links to `{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=email` (Confirm signup) and `{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=recovery` (Reset password). `/auth/confirm` still handles these: when `token_hash` is present it verifies it on the server with `verify_otp`, with no JavaScript. Both paths work side by side. Use `{{ .RedirectTo }}` (the app sends `SITE_URL/auth/confirm`) rather than `{{ .SiteURL }}`, so emails sent during local development link back to your local server.

Notes:
- Supabase's built-in email sender only allows a few emails per hour for the whole project. Both limits come back as HTTP 429 with the same code, `over_email_send_rate_limit`, so `auth_service._friendly` tells them apart by the message:
  - `email rate limit exceeded` (hourly cap): "We've hit the email sending limit. Please try again in about an hour."
  - `For security purposes, you can only request this after N seconds.` (per-address cooldown): "Please wait a minute before trying again."
  Both show on sign up, resend verification and forgot password. A custom SMTP provider removes the hourly cap.
- The login is stored only in a signed cookie (HttpOnly, SameSite=Lax, Secure on https). `SECRET_KEY` must be set on Vercel, or sessions break.

---

## Database and Storage (Supabase migrations)

Every database and storage change is a SQL file in `supabase/migrations/`, committed to the repo **and** applied to the Supabase project. Claude Code applies them through its Supabase access (the Supabase MCP), so nobody runs SQL by hand. Keep the file and the applied migration identical; to change something, add a new file instead of editing an applied one.

| File | What it does |
|---|---|
| `20261122_01_categories_expenses.sql` | `categories` and `expenses` tables, checks and indexes, Row Level Security (each user only sees their own rows), the shared `set_updated_at()` trigger, the 7 default categories (trigger on `auth.users` for new sign-ups, backfill for existing users), and the functions `dashboard_totals`, `category_expense_counts` and `delete_category` |
| `20261122_02_category_icons_storage.sql` | the public `category-icons` Storage bucket and its policies |
| `20261122_03_analytics_function.sql` | `get_month_analytics(p_month_start, p_today)` for the analytics page (Spec 04) |

Notes:
- The app only uses the **anon key** plus the logged-in user's access token (sent per request by `get_user_supabase()`), so RLS applies as that user. The `service_role` key is never used.
- `categories.is_fallback` marks each user's undeletable "Other" category (it can be renamed). Deleting a category moves its expenses there, atomically, in the `delete_category` function.
- **Storage bucket `category-icons`:** public read (icon URLs need no signing), but a user can only write inside their own folder `{user_id}/`. Objects are `{user_id}/{random}.webp`, resized by the app to 128×128 WEBP (Pillow). The bucket accepts only `image/webp` up to 512 KB.
- Money is stored as `numeric(12,2)` and handled as `Decimal` in Python. A month's list is fetched in one request (PostgREST returns at most 1000 rows, far more than a month of personal expenses); there is no pagination yet.
- `get_month_analytics(p_month_start date, p_today date) returns jsonb` returns everything `/analytics` needs in one call: totals, daily series (zeros included, with running totals), categories, the previous month and the last 6 months. It is `security invoker` (RLS applies), callable only by `authenticated`, and returns **money as text** so Python reads exact `Decimal`s. Flask passes `p_today` (Karachi time), and a month outside the user's range falls back to the current month.
- All "today" and "current month" logic uses Asia/Karachi time (`app/utils/dates.py`, with the `tzdata` package), because Vercel runs in UTC.

---

## Chart.js (analytics page only)

`/analytics` loads **Chart.js 4.6.1** from cdnjs, pinned with Subresource Integrity, and only on that page (`app/templates/analytics.html`):

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.6.1/chart.umd.min.js"
        integrity="sha512-vMRyUfXe50uUhhDC+fk6UYBA/1VPj+I7Jn+wK0A3+wSVeUgT9OCz/xoF2M8KFvrmUOlb4Anv0FQUw8NafuzYPw=="
        crossorigin="anonymous" referrerpolicy="no-referrer" defer></script>
```

Flask renders the stats, legend and "Show data" tables, and puts the chart data in `<script type="application/json" id="analytics-data">`. `public/static/js/analytics.js` draws the charts from it. If the CDN is blocked, the page still works without the charts.

**To upgrade:** pick a version, get the `chart.umd.min.js` hash from `https://api.cdnjs.com/libraries/Chart.js/<version>?fields=sri` (not the top-level `sri` field, which is for `chart.min.js`), update both attributes, then check the hash locally:

```powershell
$f = Join-Path $env:TEMP "chart.js"
curl.exe -sSfL "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/<version>/chart.umd.min.js" -o $f
"sha512-" + [Convert]::ToBase64String([Security.Cryptography.SHA512]::Create().ComputeHash([IO.File]::ReadAllBytes($f)))
```

---

## Tailwind CSS (standalone CLI, no Node needed)

The compiled `public/static/css/output.css` is committed, so you only need the CLI when you change templates or styles.

**1. Download the CLI once** (v4.3.5) to the repo root. It's git-ignored.

```powershell
# Windows
curl.exe -sSLo tailwindcss.exe https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.5/tailwindcss-windows-x64.exe
```

```bash
# macOS (Apple Silicon); use tailwindcss-macos-x64 for Intel
curl -sSLo tailwindcss https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.5/tailwindcss-macos-arm64 && chmod +x tailwindcss
# Linux
curl -sSLo tailwindcss https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.5/tailwindcss-linux-x64 && chmod +x tailwindcss
```

**2. Build (minified).** Run this before every commit that touches templates or styles.

```powershell
.\tailwindcss.exe -i app/styles/input.css -o public/static/css/output.css --minify
```

**3. Watch while developing.** Run it in a second terminal, next to `flask run`.

```powershell
.\tailwindcss.exe -i app/styles/input.css -o public/static/css/output.css --watch
```

On macOS and Linux, use `./tailwindcss` instead of `.\tailwindcss.exe`.

Design tokens (colors `cream`, `cream-dark`, `ink`, `ink-soft`, `ember`, `ember-dark`, plus the fonts) live in the `@theme` block of `app/styles/input.css`. Component classes live under `@layer components`: `btn-primary`, `btn-dark`, `btn-ghost`, `card`, `card-dark`, `underline-swoosh`, `container-page`, the form classes `auth-card`, `form-label`, `form-input`, `form-error`, `flash-success`, `flash-error` and `link-ember`, and the dashboard classes `expense-row`, `category-chip`, `emoji-chip`, `icon-circle`, `fab`, `avatar`, `select-pill`, `spent-tab`, `badge`, `note-box`, `dialog-panel` and `dialog-confirm`. Tailwind v4 has no `tailwind.config.js`.

---

## Deploying to Vercel

1. **Push to GitHub.** Create an empty repo on github.com, then:
   ```bash
   git remote add origin https://github.com/<you>/pocketly.git
   git push -u origin main
   ```
2. **Import in Vercel.** Go to vercel.com → Add New → Project, and import the repo. Vercel detects **Flask** from `requirements.txt` and uses `wsgi.py` as the entry point. Leave the Build Command empty, because the CSS is already compiled.
3. **Add environment variables** under Project → Settings → Environment Variables: `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SITE_URL=https://<your-app>.vercel.app` and `FLASK_ENV=production`. Then redeploy.
4. Every push to `main` deploys automatically, and other branches get preview URLs.

How it's served on Vercel:
- All page requests go to the Flask app (`wsgi.py`).
- Everything in `public/` is served by Vercel's CDN at the same path, so `public/static/css/output.css` is available at `/static/css/output.css`. That's the same URL Flask serves locally.
- The Python version comes from `.python-version`.
