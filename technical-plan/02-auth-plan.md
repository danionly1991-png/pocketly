# Spec 02 — Auth: Technical Implementation Plan

> **First step after approval:** save this plan to `technical plan/02-auth-plan.md` in the project root, as requested (that folder already exists and is empty). Plan mode only lets me write here, so the copy happens first when implementation starts.

## Context

Spec 01 shipped the Flask app factory, design system, landing page and placeholder routes. `/login`, `/signup` and `/dashboard` are still "coming soon" pages, and `get_supabase()` exists but nothing uses it yet. Spec 02 adds real Supabase email + password auth that runs on the server in Flask: sign up, email verification, login, logout, forgot/reset password, a protected dashboard placeholder and a navbar that changes when you're logged in. Everything must work on Vercel serverless: **cookie-only sessions, no in-memory state between requests, and a fresh Supabase client per request.**

Findings from the codebase that shape this plan:
- `app/supabase_client.py` caches **one global client** (`_client`). The supabase client keeps the logged-in session in that object's memory, so on a warm serverless instance one user's session could leak into another user's request. **This must change.**
- `supabase` 2.34.1 is installed (latest on PyPI). `create_client()` defaults to `flow_type="pkce"`, `persist_session=True`, `auto_refresh_token=True` (background timer). None of these fit a stateless server.
- Templates link to `placeholders.login` / `placeholders.signup` in `components/navbar.html:8-9` and `landing.html:23,24,49`.
- `Config.FLASK_ENV` defaults to `"production"` when unset, so `DEBUG` is False locally unless `FLASK_ENV=development`.
- Existing pieces to reuse: `button()`, `accent()` and `icon()` in `components/macros.html`; `.card`, `.btn-primary`, `.btn-dark`, `.btn-ghost`, `.btn-sm` and `.container-page` in `app/styles/input.css`; the `coming_soon.html` card layout pattern; the `inject_globals` context processor in `app/__init__.py`.

---

## 1. Files to create or modify (in order)

### Step 1: Dependencies and config
1. **`requirements.txt`**: add `flask-wtf==1.3.0` and `email-validator==2.4.0` (the latest versions). Also pin the `WTForms` version that gets installed (read it from `pip freeze`), since CLAUDE.md asks for pinned versions. `email-validator` is needed by WTForms' `Email()` validator. Install them, then check they import on Python 3.14.
2. **`app/config.py`**: add
   - `SITE_URL`, from the environment with the trailing `/` stripped. If it's empty, log a warning (email links would break).
   - `SESSION_COOKIE_HTTPONLY = True` and `SESSION_COOKIE_SAMESITE = "Lax"`.
   - `SESSION_COOKIE_SECURE = SITE_URL.startswith("https://")`, so cookies are Secure on Vercel and still work over plain-http localhost. See conflict C6.
   - `PERMANENT_SESSION_LIFETIME = timedelta(days=7)` (C9).
   - `WTF_CSRF_TIME_LIMIT = None`, so the CSRF token lasts as long as the session cookie. Forms left open for more than an hour won't fail.
   - Update the `SECRET_KEY` warning text so it says sessions and login are now live.
3. **`.env.example`**: add `SITE_URL=http://127.0.0.1:5000` with a comment (production uses `https://<app>.vercel.app`). Update the "Not used yet" comments.

### Step 2: Supabase client per request
4. **`app/supabase_client.py`**: rewrite `get_supabase()`:
   - Remove the global `_client`. Build a new client per request and cache it on `flask.g` (`g._supabase`), so several helpers in one request share it but it never outlives the request.
   - Create it with `create_client(url, key, options=ClientOptions(flow_type="implicit", persist_session=False, auto_refresh_token=False))`. `ClientOptions` comes from `from supabase import ClientOptions`, which is `SyncClientOptions`.
     - `implicit`: with PKCE, `sign_up` and `reset_password_for_email` store a code verifier in the client's memory storage, and that storage is gone by the next request. Our email links use `token_hash`, which needs no verifier (see section 2).
     - `auto_refresh_token=False`: no background timer threads on serverless. We refresh ourselves.
   - Keep `supabase_configured()` and the "return `None` and log a warning" behaviour.
   - Update the module docstring.

### Step 3: Service layer (thin routes, as CLAUDE.md asks)
5. **`app/services/__init__.py`** (new, empty) and **`app/services/auth_service.py`** (new). This is the only module that talks to Supabase Auth.
   - `class AuthError(Exception)` carries `.user_message`, `.code` and `.field` (an optional form field to attach the error to).
   - It has one function per operation (see section 2). Each function calls `get_supabase()`, raises `AuthError("Login isn't available right now…")` if that returns `None`, and catches `supabase_auth.errors.AuthApiError` / `AuthError` / `httpx` errors.
   - Errors are logged as `code` plus `status` only, never request bodies or passwords, and translated through a single `_friendly(error)` map:
     | Supabase code | Friendly message |
     |---|---|
     | `invalid_credentials` | "Incorrect email or password." |
     | `email_not_confirmed` | "Please verify your email first." |
     | `over_email_send_rate_limit`, `over_request_rate_limit`, HTTP 429 | "Please wait a minute before trying again." |
     | `weak_password` | Password field error (spec text) |
     | `same_password` | "Your new password must be different from the old one." |
     | `otp_expired`, `otp_invalid`/403 on verify | → link-error page |
     | anything else | "Something went wrong. Please try again." |
   - Returns a small `SessionData` dataclass: `access_token`, `refresh_token`, `expires_at`, `user_id`, `email`, `name`. It's built from a `supabase_auth.types.Session` by `_to_session_data(session)`. `name` comes from `user.user_metadata.get("full_name")`, falling back to the part of the email before `@`.

### Step 4: Auth helpers
6. **`app/auth_utils.py`** (new):
   - Session keys: `session["auth"]` holds the `SessionData` dict, `session["recovery"]` holds the recovery tokens, and `session["pending_email"]` holds the address for check-email and resend.
   - `save_login(data)` clears the session (stops session fixation), stores `auth` and sets `session.permanent = True`. `clear_login()` clears the session.
   - `load_current_user()` is registered with `app.before_request` and skips the `static` endpoint:
     - It reads `session["auth"]` with **no network call**.
     - If `expires_at - 60s <= now`, it calls `auth_service.refresh(refresh_token)`. On success it saves the new tokens. On failure it clears the session and sets `g.session_expired = True`.
     - It sets `g.current_user`, a frozen `CurrentUser(id, email, name)` dataclass or `None`.
   - `current_user()` returns `g.current_user`.
   - `login_required(view)`: if there's no user, it flashes "Please log in to continue." and redirects to `url_for("auth.login", next=request.full_path)` (with a trailing `?` stripped). Spec 03 can reuse it as is.
   - `logged_out_only(view)`: if there is a user, it redirects to `auth.dashboard`.
   - `safe_next(target) -> str | None` accepts only paths that start with a single `/` and contain no `//` prefix, no `\`, no scheme or netloc (checked with `urlsplit`) and no control characters. Anything else gives `None`, which falls back to `/dashboard`.
7. **`app/forms.py`** (new). Flask-WTF `FlaskForm` classes with the exact error messages from spec section 7:
   - `SignupForm`: name, email, password, confirm.
   - `LoginForm`: email, password. It only checks the fields aren't empty, so we don't hint at the password rules.
   - `ForgotPasswordForm`: email.
   - `ResetPasswordForm`: password, confirm.
   - `ResendForm`: optional email (C4).
   - Filters: `strip` on name, `strip` + `lower` on email.
   - A reusable `password_rule` validator: `len >= 8` plus `[A-Za-z]` and `\d` regexes.
   - Email uses `Email(check_deliverability=False)`, so there are no DNS lookups on serverless.
   - Password fields use `PasswordField`, which never re-renders its value. That covers "never re-fill passwords".

### Step 5: Routes
8. **`app/routes/auth.py`** (new): `auth_bp`. The routes stay thin: validate the form, call the service, flash, redirect.
   - `/signup` (`@logged_out_only`): on a valid form, call `auth_service.sign_up`, set `session["pending_email"]`, and redirect to `auth.check_email`. A rate-limit or weak-password error re-renders the form with a field or flash error. Name and email are kept, passwords are not.
   - `/check-email` GET: shows `pending_email` if there is one.
   - `/resend-verification` POST: uses `pending_email` or the email typed into the form. The result is always the same message, "If that account needs verifying, we've sent a new link." The rate-limit message is the one exception.
   - `/auth/confirm` GET:
     - `type` must be `email` or `signup` (both mean signup verification) or `recovery`. Any other type, or a missing `token_hash`, shows `link_error.html` with status 400.
     - Signup: `save_login`, flash "Email verified. Welcome to Pocketly!", redirect to the dashboard.
     - Recovery: store `session["recovery"]` (tokens + `expires_at`), **not** `auth`, so the user isn't logged in until they set a password. Redirect to `/reset-password`.
     - Failure: `link_error.html` with a `kind` (signup or recovery), so the button goes to `/check-email` or `/forgot-password`.
   - `/login` (`@logged_out_only`): the form posts to `url_for('auth.login', next=next)`.
     - Success: `save_login` → `safe_next(next)` or the dashboard.
     - `email_not_confirmed`: set `pending_email` and show the error with a "Resend verification email" link to `/check-email`.
   - `/logout` POST: call `auth_service.sign_out(access_token)` and ignore any error, then always `clear_login()`. Flash "You've been logged out" and redirect to `main.landing`. If you're already logged out, it just redirects.
   - `/forgot-password` (`@logged_out_only`): call `auth_service.send_reset`, then always flash "If an account exists for that email, we've sent a reset link." and re-show the page. The rate-limit message is the one exception.
   - `/reset-password` GET/POST:
     - If there's no `session["recovery"]`, or its refresh token is unusable, redirect to `/forgot-password`.
     - POST: `auth_service.update_password(recovery_tokens, new_pw)` returns a fresh `SessionData`. Then `pop("recovery")`, `save_login`, flash "Password updated.", and redirect to the dashboard.
   - `/dashboard` (`@login_required`): renders `dashboard.html`.
9. **`app/routes/placeholders.py`**: remove `login`, `signup` and `dashboard` from `PAGES` and their routes. Keep only `/analytics` and update the docstring.
10. **`app/routes/__init__.py`**: export `auth_bp`.
11. **`app/__init__.py`**:
    - `CSRFProtect(app)`.
    - Register `auth_bp`.
    - `app.before_request(load_current_user)`.
    - Extend `inject_globals` with `current_user` and `get_started_url` (the dashboard if logged in, otherwise signup), so templates stay free of logic.
    - An `@app.errorhandler(CSRFError)` that flashes "Your session timed out. Please try again." and redirects to `request.path`.
    - Update the startup warning text.

### Step 6: Styles and components
12. **`app/styles/input.css`**: add to `@layer components`:
    - `.form-label`.
    - `.form-input`: `w-full rounded-xl border border-cream-dark bg-white px-4 py-3`, `focus:ring-2 focus:ring-ember`, and an invalid state.
    - `.form-error`: small `text-ember-dark`.
    - `.auth-card`: `card`, `w-full max-w-[420px]`, rounded-2xl, soft shadow.
    - `.flash-success`: `bg-cream text-ink`. `.flash-error`: an ember tint, `bg-ember/10 text-ember-dark`.
    - `.link-ember`.
13. **`app/templates/components/form_field.html`** (new): a `field(form_field, type=None, autocomplete=None, password_toggle=False)` macro that renders the label, input, error list and `aria-describedby`/`aria-invalid`.
14. **`app/templates/components/flash.html`** (new): loops over `get_flashed_messages(with_categories=True)` and adds `role="status"`.
15. **`app/templates/components/macros.html`**: add `auth_card(heading_before, accent_word)` as a `{% call %}` macro for the shared layout (centered section, card, heading with the serif accent, flash include). Add a `logout_button(variant)` macro that renders a POST form with `{{ csrf_token() }}`. The navbar and the dashboard both use it.
16. **`public/static/js/password-toggle.js`** (new, about 15 lines): finds `[data-password-toggle]` buttons and switches the related input between `type=password` and `type=text`, changing the label between "Show" and "Hide". The buttons are rendered `hidden` and the script un-hides them, so the forms still work with JS off. Pages load it from their `scripts` block.

### Step 7: Pages
17. **`app/templates/auth/`** (new): `signup.html`, `check_email.html`, `login.html`, `forgot_password.html`, `reset_password.html` and `link_error.html`. Each one extends `base.html`, uses `auth_card` and `field`, and has headings and copy exactly as in spec section 8.2. The `check_email` page always shows the line "If this email isn't already registered, you'll get a verification email." (C3).
18. **`app/templates/dashboard.html`** (new): "Hi, *{name}.*", "Your month will show up here soon." and `logout_button("dark")`.
19. **`app/templates/components/navbar.html`**: two states based on `current_user`. Logged in shows Dashboard (ghost) and Log out (dark, a POST form), and the logo links to the dashboard. Logged out keeps the Spec 01 buttons, now pointing at `auth.*` routes.
20. **`app/templates/landing.html`**: the "Get started" buttons use `get_started_url`, and "Log in" points to `auth.login`.

### Step 8: Build, docs and housekeeping
21. Rebuild `public/static/css/output.css` with `--minify` and commit it.
22. **`README.md`**:
    - Add `SITE_URL` to the env table and to the Vercel env-var step.
    - Add a "Supabase Auth setup" section (section 4 below).
    - Update the file tree (`auth_utils.py`, `forms.py`, `services/`, `auth/`).
23. **`CLAUDE.md`**: mark roadmap row 02 as Done. Update the Architecture section: placeholders now only serve `/analytics`; new `services/`, `auth_utils.py` and `forms.py`; `get_supabase()` is now per request; `SITE_URL` added to the env vars.
24. **`vercel.json`** (optional, one line): add `technical plan/**` to `excludeFiles` so plan docs stay out of the function bundle.
25. Commits, in small focused pieces:
    - `chore(deps): add flask-wtf`
    - `feat(auth): per-request supabase client`
    - `feat(auth): service + helpers`
    - `feat(auth): routes and pages`
    - `feat(nav): logged-in navbar`
    - `docs: supabase auth setup`

---

## 2. Supabase Python client methods (checked against installed `supabase` / `supabase-auth` 2.34.1)

All calls go through `client.auth` on the per-request client.

| Operation | Exact call | Returns / notes |
|---|---|---|
| Sign up | `auth.sign_up({"email": e, "password": p, "options": {"data": {"full_name": name}, "email_redirect_to": SITE_URL + "/auth/confirm"}})` | `AuthResponse(user, session)`. With Confirm email ON, `session` is `None`. **An email that's already registered does not raise an error.** Supabase returns an obfuscated user with `identities == []`, which suits the spec's "don't reveal" rule; we don't inspect it. |
| Verify email or recovery link | `auth.verify_otp({"token_hash": th, "type": "email" \| "recovery"})` | `AuthResponse` with a `session` (access + refresh token, `expires_at`, `user`). `EmailOtpType` also accepts `"signup"`. Expired or used links raise `AuthApiError`, usually code `otp_expired`, status 403. |
| Resend verification | `auth.resend({"type": "signup", "email": e, "options": {"email_redirect_to": SITE_URL + "/auth/confirm"}})` | `AuthOtpResponse`. A rate limit raises `AuthApiError` with code `over_email_send_rate_limit` / status 429. |
| Log in | `auth.sign_in_with_password({"email": e, "password": p})` | `AuthResponse`. Errors: `invalid_credentials`, and `email_not_confirmed` (Supabase checks the password first, so this doesn't reveal whether the account exists). |
| Log out | `auth.admin.sign_out(access_token, "local")` | **Differs from the spec's assumption.** `auth.sign_out()` needs a session already loaded into the client, which would mean an extra `set_session` network call or burning a refresh. `admin.sign_out(jwt, scope)` just POSTs `/logout` with the **user's own JWT**. It doesn't need the service_role key, despite the `admin` name. `"local"` revokes only this device's session. |
| Reset email | `auth.reset_password_for_email(e, {"redirect_to": SITE_URL + "/auth/confirm"})` | Returns `None`. The option key is **`redirect_to`**, not `email_redirect_to`. Unknown emails don't raise an error. |
| Update password | `auth.set_session(access, refresh)` then `auth.update_user({"password": new})` | `update_user` **takes no token argument**: it reads the session stored in the client and raises `AuthSessionMissingError` without one. So we call `set_session` first, which validates or refreshes the token. Afterwards we read the fresh tokens with `auth.get_session()`. `UserResponse(user)`. Errors: `same_password`, `weak_password`. |
| Refresh | `auth.refresh_session(refresh_token)` | `AuthResponse(session, user)`. An invalid or used refresh token raises `AuthApiError`, and a missing one raises `AuthSessionMissingError`. Refresh tokens are **single-use** (there's a short reuse window). |

How this differs from the spec:
- **PKCE is the default** in `create_client`, so we set `flow_type="implicit"` (Step 2).
- Logout uses `admin.sign_out(jwt)` instead of `sign_out()`.
- `update_user` needs `set_session` first.
- The reset option key is `redirect_to`.

The `token_hash` + `verify_otp` server flow in the spec still matches Supabase's current server-side guidance, so we keep it.

---

## 3. Sessions and token refresh on Vercel

- **Storage:** Flask's signed cookie only, holding `auth = {access_token, refresh_token, expires_at, user_id, email, name}`. That's about a 1 KB JWT plus small fields, roughly 2 KB after signing and base64, which is under the 4 KB cookie limit. We never store the whole `User` object.
  - The cookie is **signed, not encrypted**. `HttpOnly` keeps it away from JS, `Secure` keeps it on HTTPS and `SameSite=Lax` blocks cross-site POSTs. `SECRET_KEY` must be set on Vercel.
- **Per request:**
  - `before_request` reads the cookie with no network call.
  - If the access token expires within 60s, it makes one `refresh_session` call. The rotated tokens go back into `session`, and Flask re-sends the cookie on the response.
  - If the refresh fails, the session is cleared. `login_required` then sends the user to `/login?next=…`.
  - With the default 1-hour JWT, that's about one refresh per hour of activity.
- **Client isolation:** a new `Client` is created per request on `flask.g` with `persist_session=False`, and no module-level client is kept. The library import is reused per process, which is fine; client *state* is never reused.
- **Refresh race:** two tabs refreshing at the same moment could both use the same single-use refresh token. Supabase's reuse window (10s by default) covers near-simultaneous requests. In the worst case the user is asked to log in again, which is acceptable.
- **Revocation:** logout revokes the refresh token on the server. An access token that was already issued stays valid until it expires (up to 1h), as Supabase documents. That's fine here because no data is attached to it yet.
- **CSRF:** Flask-WTF stores its token in the same cookie session, and every form, including the navbar logout form, renders `csrf_token()`.

---

## 4. Manual Supabase dashboard steps (also go in the README)

1. **Authentication → Sign In / Providers → Email:** enabled, **Confirm email ON**. Optionally set the minimum password length to 8 to match our rule.
2. **Authentication → URL Configuration:**
   - **Site URL** = `https://<your-app>.vercel.app`.
   - **Redirect URLs:** add `https://<your-app>.vercel.app/**`, `http://127.0.0.1:5000/**` and `http://localhost:5000/**`.
3. **Authentication → Email Templates → Confirm signup:** set the link to
   `<a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=email">Confirm your email</a>`
4. **Email Templates → Reset password:** set the link to
   `<a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=recovery">Reset your password</a>`
5. **Vercel → Environment Variables:** `SITE_URL=https://<your-app>.vercel.app`, plus the existing `SECRET_KEY`, `SUPABASE_URL` and `SUPABASE_ANON_KEY`. Then redeploy.
6. Note: the built-in mailer allows only a few emails per hour. Rate-limit errors during testing are expected; custom SMTP can come later.

---

## 5. Testing checklist (mapped to spec section 11)

There's no test suite. I'll run a throwaway Flask test-client script from the scratchpad (not committed) for the checks that don't need the network, then test the rest by hand in the browser locally, and again on Vercel.

**Sign up & verification**
- [ ] Bad name, email, password or mismatched confirm shows each exact message under its field; name and email are kept and the password fields are empty. *(test client + browser)*
- [ ] A valid signup leads to `/check-email` showing the address, and the user appears in Supabase → Users with `full_name` in raw user metadata.
- [ ] Signing up with an existing email shows the same check-email page and the same hint.
- [ ] Clicking the email link lands on `/dashboard`, logged in, with the "Email verified…" flash.
- [ ] Reusing the same link, a link with a changed `token_hash`, or a `type=foo` link shows the styled link-error page.
- [ ] Resend works. Clicking it several times quickly shows "Please wait a minute…" with no traceback.

**Login & logout**
- [ ] A verified user lands on the dashboard showing "Hi, {name}."
- [ ] A wrong password and an unknown email give the identical "Incorrect email or password."
- [ ] An unverified user with the correct password sees "Please verify your email first." plus a resend link.
- [ ] Logout POST clears the cookie, lands on `/` with the flash, and the back button followed by `/dashboard` sends you to login. A GET to `/logout` returns 405.

**Password reset**
- [ ] Known and unknown emails get the identical message.
- [ ] The reset link opens `/reset-password`. The new password logs in afterwards and the old one fails.
- [ ] Opening `/reset-password` directly redirects to `/forgot-password`.

**Protection & navigation**
- [ ] Logged out, `/dashboard` redirects to `/login?next=/dashboard`, and logging in returns you to `/dashboard`.
- [ ] Logged in, `/login`, `/signup` and `/forgot-password` redirect to `/dashboard`.
- [ ] `next=//evil.com`, `https://evil.com`, `/\evil.com` and `javascript:alert(1)` all fall back to `/dashboard`. *(test client)*
- [ ] Navbar shows Log in + Get started when logged out, and Dashboard + Log out when logged in. The logo and the landing CTAs go to `/dashboard` when logged in.
- [ ] Token refresh: temporarily change the stored `expires_at` (or wait an hour) and confirm the page still loads and the cookie gets new tokens. With a bad refresh token, you're sent to login.

**Security & quality**
- [ ] Every POST without a CSRF token is rejected with a friendly flash. *(test client)*
- [ ] DevTools shows the cookie as `HttpOnly` and `SameSite=Lax`, and `Secure` on Vercel. `document.cookie` doesn't show the session.
- [ ] A grep of the logs and flash calls shows no passwords. Password inputs never have a `value` attribute.
- [ ] Every new page works at a 375px width with no horizontal scroll (DevTools device mode).

**Deployment**
- [ ] The full flow works locally (`SITE_URL=http://127.0.0.1:5000`) and on Vercel (`SITE_URL=https://…`), with emails linking to the right host each time.
- [ ] The README documents the dashboard steps and `SITE_URL`.

---

## 6. Conflicts with the spec, and decisions

| # | Conflict | Decision | Why |
|---|---|---|---|
| C1 | `get_supabase()` caches one global client, but spec section 12 requires one client per request | Make it per request on `flask.g`, with `persist_session=False` and `auto_refresh_token=False` | A global client keeps the last user's session in memory on warm serverless instances, so sessions could leak between users |
| C2 | Email templates in spec sections 6.2 and 6.5 use `{{ .SiteURL }}` | Use **`{{ .RedirectTo }}`** (the value is `SITE_URL/auth/confirm`, which we already pass) | With one Supabase project, `.SiteURL` always points to production, so emails sent from local dev would link to Vercel. `.RedirectTo` follows each environment's `SITE_URL`, and Supabase falls back to the Site URL if the redirect isn't allow-listed |
| C3 | Spec section 6.1.5 wants a "may already be registered" message, while section 8.2 says "We sent a link to {email}" | Show both on check-email, **always** | Supabase doesn't tell us whether the email exists, and changing the page based on that would reveal accounts |
| C4 | `/check-email` is for "Anyone", but visitors who arrive without signing up have no address on file | If there's no `pending_email`, the resend form shows an email input | Lets the link-error page and direct visitors request a new link |
| C5 | Spec section 6.5.4 says to save "a temporary session flag" for recovery | Store the recovery **tokens** under a separate `recovery` key, not `auth`, and promote them to a login after `update_user` | `update_user` needs the user's tokens, and the user shouldn't count as logged in until they set a new password |
| C6 | "Secure in production", but `FLASK_ENV` defaults to production and local runs are plain http | `SESSION_COOKIE_SECURE = SITE_URL.startswith("https://")` | Ties the setting to the real scheme, so local logins keep working and Vercel always gets a Secure cookie |
| C7 | The spec example uses `http://localhost:5000`, but `flask run` and CLAUDE.md use `127.0.0.1:5000` | Default to `SITE_URL=http://127.0.0.1:5000` and allow-list both hosts | Cookies are per host. Clicking an email link to `localhost` while browsing on `127.0.0.1` would look like a separate login |
| C8 | Spec section 10's file list has no `services/`, but CLAUDE.md says to put Supabase logic in `app/services/` | Add `app/services/auth_service.py` | Keeps routes thin and gives Spec 03 a pattern to follow. It's an addition, not a restructure |
| C9 | The spec doesn't say how long a login lasts | Use a 7-day permanent session | Otherwise the cookie disappears when the browser closes. Seven days is a safe middle ground and easy to change |
| C10 | The spec says "tiny inline JS" for the Show toggle, used on 3 pages | One file, `public/static/js/password-toggle.js`, loaded from each page's `scripts` block | Avoids copying the same script 3 times. It's served from the CDN and needs no framework |
| C11 | `/auth/confirm` uses GET (per spec), and some email scanners pre-open links, which can use up the one-time token | Keep GET as the spec says, and treat it as a known risk | The styled link-error page and resend cover it. If it happens in practice, a later spec can add a "Confirm" button page |
| C12 | `/analytics` isn't listed as protected | Leave it as a public placeholder | The spec says to keep it as is. Whichever spec builds analytics will add `@login_required` |
