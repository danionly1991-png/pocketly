# Spec 02 — Sign up, Email Verification & Login

**Project:** Pocketly — a personal expense tracker for managing monthly pocket money
**Spec status:** Ready for planning
**Date:** 2026-11-17
**Depends on:** Spec 01 — Project Base & Landing Page
**Next spec:** 03 — Dashboard & add expense (to be written)

---

## 1. Purpose

Let people create a Pocketly account with email and password, verify their email, log in, log out and reset a forgotten password. After login, users land on a protected dashboard placeholder. This gives every later feature (expenses, analytics) a real logged-in user to attach data to.

## 2. Goals

1. Sign-up form: **name, email, password, confirm password**.
2. Email verification through Supabase Auth before the user can log in.
3. Login with email + password; logout.
4. "Forgot password?" flow: request a reset email, then set a new password.
5. A protected `/dashboard` placeholder that greets the user by name and has a Log out button.
6. Logged-out users who open protected pages are sent to `/login`; logged-in users who open `/login` or `/signup` are sent to `/dashboard`.
7. Navbar changes depending on whether the user is logged in.

## 3. Out of scope (later specs)

- Google / social login, magic links
- Expense tables, monthly budget, real dashboard content (Spec 03+)
- Profile/settings page, change email, delete account
- A separate `profiles` database table (the name is stored in Supabase user metadata for now)

---

## 4. Tech approach

| Concern | Choice | Notes |
|---|---|---|
| Auth provider | **Supabase Auth** (email + password) | Uses the `supabase` Python client already set up in Spec 01 |
| Where auth runs | **Server side, in Flask** | Forms post to Flask routes; Flask calls Supabase. No auth JavaScript in the browser |
| Session storage | Flask signed cookie session | Store the Supabase `access_token`, `refresh_token` and basic user info (id, email, name). Vercel is serverless, so **no in-memory or file sessions** |
| Name storage | Supabase `user_metadata.full_name` | Passed in the sign-up call's `options.data` |
| CSRF protection | **Flask-WTF** (`CSRFProtect`) | Every POST form includes a CSRF token |
| Form validation | Server side (Flask-WTF forms or plain validation) | Show errors inline under fields |

Cookie settings: `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`, `SESSION_COOKIE_SECURE=True` in production.

New env var: `SITE_URL` (e.g. `http://localhost:5000` locally, the Vercel URL in production), used for email redirect links. Add it to `config.py`, `.env.example` and the README.

> If the current Supabase docs recommend a different server-side flow than the one below, follow the docs and explain the change in the plan.

---

## 5. Routes

New blueprint: `app/routes/auth.py`. Remove `/login`, `/signup` and `/dashboard` from `placeholders.py` (keep `/analytics` as a placeholder).

| Route | Method | Access | What it does |
|---|---|---|---|
| `/signup` | GET, POST | Logged-out only | Show form / create account, then redirect to `/check-email` |
| `/check-email` | GET | Anyone | "Check your inbox" page with a **Resend email** button |
| `/resend-verification` | POST | Anyone | Resends the verification email |
| `/auth/confirm` | GET | Anyone | Handles links from emails (verification and password reset). With `token_hash` it verifies on the server; without it, it shows the "Verifying..." page (see 6.7) |
| `/auth/session` | POST | Anyone (CSRF-protected) | Receives tokens read from the URL fragment, validates them with Supabase, logs in or starts the reset flow, replies with JSON `{redirect}` |
| `/auth/link-error` | GET | Anyone | The styled "link expired" page |
| `/login` | GET, POST | Logged-out only | Show form / log in, then redirect to `/dashboard` (or the `next` page) |
| `/logout` | POST | Logged-in | Signs out of Supabase, clears the session, redirects to `/` with a "You've been logged out" message |
| `/forgot-password` | GET, POST | Logged-out only | Ask for email, send reset link |
| `/reset-password` | GET, POST | Only after a valid reset link | Set a new password |
| `/dashboard` | GET | **Logged-in only** | Placeholder: "Hi, {name} 👋" + Log out button |

Logout must be a **POST** (a small form button), not a GET link.

---

## 6. Flows

### 6.1 Sign up
1. User fills in name, email, password, confirm password.
2. Validate (see section 7). On error, re-show the form with entered name and email kept (never re-fill passwords).
3. Call Supabase `sign_up` with email, password, `options.data.full_name = name`, and `email_redirect_to = SITE_URL + /auth/confirm`.
4. Redirect to `/check-email`, showing the address the email was sent to.
5. If the email is already registered, show a general message: "If this email isn't already registered, you'll get a verification email." Don't reveal whether an account exists.

### 6.2 Email verification
1. Supabase sends the verification email (Confirm email must be **enabled** in the Supabase dashboard).
2. Update the Supabase "Confirm signup" email template so the link points to the Flask app:
   `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email`
3. `/auth/confirm` calls Supabase `verify_otp` with the `token_hash` and `type`.
4. On success: save the session and redirect to `/dashboard` with "Email verified. Welcome to Pocketly!"
5. On failure or an expired link: show a styled error page with a link to request a new email.

> **Plan note (updated):** custom email templates need custom SMTP, which we don't have. So the default Supabase flow is used (see 6.7). The `token_hash` steps in 6.2 and 6.5 stay supported for when templates can be edited.

### 6.3 Resend verification
- `/check-email` has a "Resend email" button (POST) that calls Supabase's resend for signup.
- If Supabase rate-limits the request, show a friendly message: "Please wait a minute before trying again."

### 6.4 Log in
1. User enters email and password.
2. Call Supabase `sign_in_with_password`.
3. On success: store the tokens and user info in the session and redirect to `next` (only if it is a safe, internal path) or `/dashboard`.
4. Wrong credentials: "Incorrect email or password." (same message for both cases).
5. Unverified email: "Please verify your email first." plus a resend link.

### 6.5 Forgot / reset password
1. `/forgot-password`: user enters email and the app calls Supabase `reset_password_for_email` with redirect to `SITE_URL + /auth/confirm`.
2. Always show the same message: "If an account exists for that email, we've sent a reset link."
3. Update the Supabase "Reset password" email template link to:
   `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery`
4. `/auth/confirm` with `type=recovery` verifies the token, saves a temporary session flag, and redirects to `/reset-password`.
5. `/reset-password`: new password + confirm. Call Supabase `update_user` with the new password, then redirect to `/dashboard` with "Password updated."
6. Opening `/reset-password` without a valid recovery session redirects to `/forgot-password`.

### 6.7 Default Supabase link flow (fragment tokens)
Supabase verifies the link itself, then redirects to `/auth/confirm#access_token=...&refresh_token=...&expires_in=3600&type=signup` (`type=recovery` for resets), or `#error=...&error_code=otp_expired&error_description=...` for a bad link. A URL fragment never reaches the server, so:
1. `/auth/confirm` without a `token_hash` renders `auth/verifying.html` ("Verifying...").
2. A small inline script reads `window.location.hash`, then clears it with `history.replaceState`.
3. Error in the hash, or missing tokens: go to `/auth/link-error`.
4. Otherwise `fetch` POST `{access_token, refresh_token, type}` to `/auth/session` with the CSRF token in `X-CSRFToken`, and follow the `redirect` in the JSON reply.
5. `/auth/session` validates the tokens with Supabase `set_session` (never trusted blindly; the access token is checked with Supabase and refreshed if expired). Invalid: `/auth/link-error`.
6. `type=signup`: save the login, flash "Email verified. Welcome to Pocketly!", redirect to `/dashboard`. `type=recovery`: set the recovery session flag (not a login), redirect to `/reset-password`.
7. Tokens are never logged.

### 6.6 Session & protection
- A `login_required` decorator (e.g. in `app/auth_utils.py`) protects `/dashboard` and future pages. Unauthenticated users are redirected to `/login?next=<path>` with "Please log in to continue."
- A `logged_out_only` decorator (or check) redirects logged-in users away from `/login`, `/signup`, `/forgot-password`.
- When the access token has expired, try refreshing it with the refresh token. If the refresh fails, clear the session and send the user to `/login`.
- Make `current_user` (or similar) available in all templates.

---

## 7. Validation rules

| Field | Rules | Error message |
|---|---|---|
| Name | Required, 2–50 characters, trimmed | "Please enter your name (2–50 characters)." |
| Email | Required, valid email format, lowercased and trimmed | "Please enter a valid email." |
| Password | Required, at least 8 characters, including at least one letter and one number | "Password must be at least 8 characters and include a letter and a number." |
| Confirm password | Must match password | "Passwords don't match." |

Also show any error Supabase returns (e.g. weak password, rate limit) as a clear, friendly message, never a raw stack trace.

---

## 8. Pages & design

All pages extend `base.html` and use the Spec 01 design system (cream background, `ink` text, `ember` accent only).

### 8.1 Auth page layout (shared)
- Centered white `card` (max width ≈ 420px) on the cream background, rounded-2xl, soft shadow.
- Heading in bold Inter with one italic serif accent word where it fits, e.g. "Welcome *back.*", "Create your *account.*"
- Short subtext in `ink-soft`.
- Inputs: full width, rounded-xl, `cream-dark` border, `ember` focus ring, clear labels above each field.
- Inline field errors in a small red/ember text under the field.
- Primary submit button: `btn-primary`, full width.
- Make a reusable form-field macro (`components/form_field.html`) for later specs.
- Flash messages: a small reusable component (`components/flash.html`) shown at the top of the card/page (success = ink/cream, error = ember tint).
- Password fields have a small "Show" toggle (tiny inline JS is OK; no frameworks).

### 8.2 Page content
| Page | Heading | Extras |
|---|---|---|
| Sign up | Create your *account.* | Name, Email, Password, Confirm password · "Already have an account? Log in" |
| Check email | Check your *inbox.* | "We sent a verification link to **{email}**." · Resend button · "Back to log in" |
| Log in | Welcome *back.* | Email, Password · "Forgot password?" link · "New to Pocketly? Create an account" |
| Forgot password | Forgot your *password?* | Email · "Back to log in" |
| Reset password | Set a new *password.* | New password, Confirm password |
| Link error | This link has *expired.* | Button to request a new email |
| Dashboard placeholder | Hi, *{name}.* | "Your month will show up here soon." · Log out button (`btn-dark`) |

### 8.3 Navbar states
- **Logged out:** unchanged from Spec 01 ("Log in" ghost + "Get started" dark).
- **Logged in:** "Dashboard" (ghost) + "Log out" (dark, POST form). The logo links to `/dashboard` instead of `/`.
- The landing page's "Get started" buttons go to `/dashboard` when the user is already logged in.

---

## 9. Supabase setup (document in README)

1. Authentication → Providers → Email: enabled, **Confirm email ON**.
2. Authentication → URL Configuration: set **Site URL** to the production URL and add `http://localhost:5000/**` to Redirect URLs.
3. Authentication → Email Templates: leave the defaults (flow in 6.7). Only if custom SMTP is added later, update the links as in sections 6.2 and 6.5.
4. Note: Supabase's built-in email sender has a low hourly limit, which is fine for development. A custom SMTP provider can be added later.

---

## 10. Files (expected)

```
app/
├── auth_utils.py            # login_required, logged_out_only, current_user, token refresh
├── forms.py                 # SignupForm, LoginForm, ForgotPasswordForm, ResetPasswordForm
├── routes/
│   ├── auth.py              # all auth routes + /dashboard
│   └── placeholders.py      # now only /analytics
└── templates/
    ├── components/
    │   ├── form_field.html
    │   ├── flash.html
    │   └── navbar.html      # updated for logged-in state
    ├── auth/
    │   ├── signup.html
    │   ├── check_email.html
    │   ├── login.html
    │   ├── forgot_password.html
    │   ├── reset_password.html
    │   └── link_error.html
    └── dashboard.html       # placeholder
```

Update `requirements.txt` (add `flask-wtf`, plus `email-validator` if needed), `config.py`, `.env.example` and `README.md`. Rebuild `output.css` after adding new Tailwind classes and commit it.

---

## 11. Acceptance criteria

**Sign up & verification**
- [ ] Sign-up form has name, email, password, confirm password with the validation rules in section 7.
- [ ] Submitting a valid form creates the user in Supabase (name visible in user metadata) and shows the "Check your inbox" page.
- [ ] Clicking the email link verifies the account and lands the user on `/dashboard`, logged in.
- [ ] Expired or invalid links show the styled link-error page.
- [ ] "Resend email" works and handles rate limits gracefully.

**Login & logout**
- [ ] Verified users can log in and land on `/dashboard` showing "Hi, {name}."
- [ ] Wrong credentials show one generic error; unverified users are told to verify first.
- [ ] Logout (POST) clears the session and returns to the landing page.

**Password reset**
- [ ] "Forgot password?" sends a reset email (same message whether or not the account exists).
- [ ] The reset link opens `/reset-password`; the new password works for the next login.

**Protection & navigation**
- [ ] `/dashboard` redirects logged-out users to `/login?next=/dashboard`, and after login they return there.
- [ ] Logged-in users visiting `/login`, `/signup` or `/forgot-password` are redirected to `/dashboard`.
- [ ] The `next` parameter only accepts internal paths (no open redirects).
- [ ] Navbar shows the right buttons for each state.

**Security & quality**
- [ ] All POST forms have CSRF protection.
- [ ] Session cookie is HttpOnly, SameSite=Lax, and Secure in production; no tokens are exposed to JavaScript.
- [ ] Passwords are never logged, flashed or re-filled into forms.
- [ ] All new pages are responsive and readable at 375px width.

**Deployment**
- [ ] Works locally and on the Vercel URL (with `SITE_URL` set correctly in both).
- [ ] README documents the Supabase settings and new env vars.

---

## 12. Notes for Claude Code (plan mode)

- Produce a plan listing every file to create or change, in order, before writing code.
- Check the current `supabase` Python client API (method names and response shapes for `sign_up`, `sign_in_with_password`, `verify_otp`, `resend`, `reset_password_for_email`, `update_user`, `refresh_session`) and adapt if they've changed.
- Create a fresh Supabase client per request (or pass the user's session explicitly) so one user's session never leaks into another request on serverless.
- Keep auth helpers reusable; Spec 03 will protect many more routes with `login_required`.
- Don't create database tables in this spec.
