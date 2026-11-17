# Pocketly

Pocketly is a simple expense tracker for managing your monthly pocket money. You log daily expenses in seconds and see exactly how this month is going.

Stack: Flask + Jinja2, Tailwind CSS v4 (standalone CLI), Supabase Auth, deployed on Vercel.

---

## Project layout

```
app/
  __init__.py          create_app() factory, registers blueprints, CSRF, 404 handler
  config.py            Config class (reads env vars / .env)
  supabase_client.py   get_supabase(): a new client per request, cached on flask.g
  auth_utils.py        login_required, logged_out_only, current user, token refresh, safe_next
  forms.py             Flask-WTF forms (signup, login, forgot/reset password)
  services/            auth_service.py: the only module that talks to Supabase Auth
  routes/              main.py (landing "/"), auth.py (auth pages + /dashboard), placeholders.py (/analytics)
  styles/input.css     Tailwind source: theme tokens (@theme) + component classes
  templates/           base.html, landing.html, dashboard.html, coming_soon.html, 404.html,
                       auth/ (signup, login, check email, forgot/reset password, link error), components/
public/static/         served at /static/* (Vercel CDN in production, Flask locally)
  css/output.css       compiled Tailwind CSS (committed)
  js/password-toggle.js  "Show/Hide" button for password fields
  img/favicon.svg
wsgi.py                entry point for Vercel and `flask run`
vercel.json            Vercel function settings
specs/                 feature specs
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
3. **Email Templates → Confirm signup:** set the link to
   ```html
   <a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=email">Confirm your email</a>
   ```
4. **Email Templates → Reset password:** set the link to
   ```html
   <a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=recovery">Reset your password</a>
   ```
5. **Vercel → Environment Variables:** set `SITE_URL=https://<your-app>.vercel.app` next to the other variables, then redeploy.

Notes:
- The templates use `{{ .RedirectTo }}` (the app sends `SITE_URL/auth/confirm`) instead of `{{ .SiteURL }}`. That way emails sent while developing locally link back to your local server, not to production.
- Supabase's built-in email sender only allows a few emails per hour. "Please wait a minute before trying again." during testing is expected. A custom SMTP provider can be added later.
- The login is stored only in a signed cookie (HttpOnly, SameSite=Lax, Secure on https). `SECRET_KEY` must be set on Vercel, or sessions break.

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

Design tokens (colors `cream`, `cream-dark`, `ink`, `ink-soft`, `ember`, `ember-dark`, plus the fonts) live in the `@theme` block of `app/styles/input.css`. Component classes live under `@layer components`: `btn-primary`, `btn-dark`, `btn-ghost`, `card`, `card-dark`, `underline-swoosh`, `container-page`, and the form classes `auth-card`, `form-label`, `form-input`, `form-error`, `flash-success`, `flash-error` and `link-ember`. Tailwind v4 has no `tailwind.config.js`.

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
