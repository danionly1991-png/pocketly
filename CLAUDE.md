# CLAUDE.md

Guidance for Claude Code in this repo. Read the relevant spec in `specs/` before building anything. `README.md` has full setup and deploy details.

## 1. Project overview

**Pocketly** is a personal expense tracker for monthly pocket money. Users log daily expenses in seconds, see how the current month is going, and get simple analytics. Currency is Pakistani Rupees (`Rs 1,234`).

Work is spec-driven: each feature gets a numbered spec in `specs/`. The flow is spec → plan mode → implement → check the spec's acceptance criteria. Don't build anything no spec covers.

## 2. Architecture

```
app/
├── __init__.py          # create_app(): CSRF, blueprints, before_request user loader, 404 handler
├── config.py            # reads env vars
├── supabase_client.py   # get_supabase(): new client per request on flask.g, None if unconfigured
├── auth_utils.py        # login_required, logged_out_only, current_user, token refresh, safe_next
├── forms.py             # Flask-WTF forms (signup, login, forgot/reset password)
├── services/            # auth_service.py: the only module that talks to Supabase Auth
├── routes/              # one blueprint per feature (main.py, auth.py, placeholders.py)
├── styles/input.css     # Tailwind source: @theme tokens + @layer components
└── templates/           # base.html, components/, auth/, landing, dashboard, coming_soon, 404
public/static/           # css/output.css (compiled, COMMITTED), js/, img/
specs/                   # numbered feature specs
wsgi.py                  # entry point for flask run and Vercel
```

- **Static files are in `public/static/`**, so `/static/...` works locally and on Vercel's CDN.
- **Tailwind v4 is CSS-first.** Tokens are in the `@theme` block of `input.css`. Shared classes are in `@layer components`: `btn-primary`, `btn-dark`, `btn-ghost`, `card`, `card-dark`, `container-page`, `underline-swoosh`, plus the form classes `auth-card`, `form-label`, `form-input`, `form-error`, `flash-success`, `flash-error`, `link-ember`.
- **Theme:** about 70% `cream`, 30% `ink`, with `ember` (#D9541E) as an accent only. Fonts are Inter, plus Instrument Serif italic for 1–3 accent words in headlines.
- **Placeholders:** `routes/placeholders.py` now serves only `/analytics`. Remove it from `PAGES` once its spec builds the real page.
- **Auth (Spec 02):** Supabase email + password, run server side. The login lives only in Flask's signed cookie (`session["auth"]`); `before_request` loads `g.current_user` and refreshes tokens when they're about to expire. Protect routes with `@login_required` from `app/auth_utils.py`. `get_supabase()` builds a fresh client per request (never share one between requests). Email links land on `/auth/confirm`. Supabase's default templates (we can't edit them without custom SMTP) put tokens in the URL fragment, so a small script on the "Verifying..." page POSTs them to `/auth/session`, which validates them with Supabase. The `token_hash` + `verify_otp` path still works if templates are customised later (see README).
- **Config:** env vars are `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SITE_URL`. A missing value logs a warning and doesn't crash the app.
- **Vercel:** `vercel.json` keeps `.venv`, `specs`, `app/styles` and `public` out of the function bundle. Python version comes from `.python-version`.

## 3. Code style

**Python**
- PEP 8, with type hints on new functions.
- Keep routes thin. Put Supabase queries and logic in helper modules (e.g. `app/services/`).
- Read config through `current_app.config`, not scattered `os.environ` calls.
- On errors, flash a friendly message and log the details. Never show tracebacks or raw Supabase errors.
- Store money as integers (whole rupees) or `Decimal`, never `float`.

**Templates and styling**
- Every page extends `base.html`. Turn repeated markup into a component or a macro in `components/macros.html`.
- Build links with `url_for()`. Keep logic in Python, not in templates.
- Use token classes (`bg-cream`, `text-ink`), not hex values. Reuse component classes. No inline `style=""`.
- No JavaScript by default. If a page needs some, put small vanilla JS in its `scripts` block.

**Git:** small, focused commits (e.g. `feat(auth): add signup form`).

## 4. Tech constraints

- Python 3.14, Flask, Jinja2, Supabase, Vercel Python runtime.
- No Node, npm, `package.json` or `tailwind.config.js`. Tailwind runs only through `tailwindcss.exe` (v4.3.5).
- No frontend frameworks (React, Vue, Alpine, HTMX) unless a spec adds one.
- Vercel has no build step: compile CSS locally and commit it.
- Serverless: no disk writes, background jobs or in-memory state between requests. Persist everything in Supabase.
- Use only the Supabase anon key, and protect every table with Row Level Security.
- Pin versions in `requirements.txt`. Add packages only when a spec needs them.
- Development is on Windows, so give commands in PowerShell syntax.

## 5. Commands

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask run --debug    # http://127.0.0.1:5000

# Tailwind: watch while developing (second terminal)
.\tailwindcss.exe -i app/styles/input.css -o public/static/css/output.css --watch
# Tailwind: minified build before committing
.\tailwindcss.exe -i app/styles/input.css -o public/static/css/output.css --minify
```

There's no test suite or linter yet. Verify by running the app against the spec's acceptance criteria.

## 6. Development roadmap

| # | Spec | Status |
|---|---|---|
| 01 | Base & landing page |  Done |
| 02 | Sign up, email verification & login |  Done |
| 03 | Expenses table + add-expense flow |  Next |
| 04 | Dashboard (current month only) |  Planned |
| 05 | Analytics | Planned |

**Spec 01 delivered:** the Flask app factory and blueprints; the Tailwind design system; `base.html` with navbar and footer; the landing page (hero, features strip, CTA); coming-soon placeholders; a styled 404; the Supabase client helper; and Vercel deployment.

**Spec 02 delivered:** sign up with email verification, login and logout, forgot/reset password, a protected `/dashboard` placeholder, a navbar that changes with login state, CSRF protection, and the reusable `login_required` / `logged_out_only` helpers.

The order of specs 03+ isn't final. When a spec is finished, update this table and the Architecture section.

## 7. Warnings / things to avoid

- Don't create `app/static/`. Static files go in `public/static/`.
- Don't forget to rebuild and commit `output.css` after template or style changes, or new classes won't show in production.
- Don't use the Tailwind Play CDN or add a `tailwind.config.js`.
- Don't commit `.env` or any key. Keep `.env.example` up to date.
- Don't use the Supabase `service_role` key, and never expose keys to the browser.
- Don't create tables without RLS policies.
- Don't call `get_supabase()` without handling `None`.
- Don't leave `SECRET_KEY` unset on Vercel. The random fallback breaks sessions, and so login.
- Don't rely on `FLASK_ENV`. Use `flask run --debug` or `FLASK_DEBUG=1`.
- Don't use `float` for money.
- Don't use `ember` for large backgrounds. It's an accent only.
- Don't build ahead of the spec, restructure folders, or add packages without explaining why in the plan.