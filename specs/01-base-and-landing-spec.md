# Spec 01 — Project Base & Landing Page

**Project:** Pocketly — a personal expense tracker for managing monthly pocket money
**Spec status:** Ready for planning
**Date:** 2026-11-17
**Depends on:** nothing (this is the first spec)
**Next spec:** 02 — Sign up, email verification & login

---

## 1. Purpose

Create the foundation of the Pocketly web app: the project structure, shared layout, design system, deployment setup, and a finished landing page. Every later feature (auth, dashboard, add expense, analytics) will plug into this base without restructuring it.

## 2. Goals

1. A Flask project with a clean, scalable folder structure.
2. A reusable design system (colors, fonts, buttons, cards) implemented with Tailwind CSS.
3. A shared base template that every page extends.
4. A minimal, polished, responsive landing page that explains what Pocketly does.
5. Placeholder pages for upcoming routes so navigation works from day one.
6. A Supabase client set up and ready (not used yet).
7. The app runs locally and deploys to Vercel from a GitHub repo.

## 3. Out of scope (later specs)

- Real sign-up, login, logout, email verification (Spec 02)
- Database tables for expenses (Spec 03+)
- Dashboard / current-month expenses page, add-expense flow, analytics
- Any user data handling

---

## 4. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Backend | Flask | Use an app factory (`create_app()`) and Blueprints |
| Templates | Jinja2 | All pages extend `base.html` |
| Styling | Tailwind CSS | Built with the **Tailwind standalone CLI** (no Node project needed); compiled CSS is committed to the repo so Vercel needs no build step |
| Database / Auth | Supabase | `supabase` Python client; keys from environment variables |
| Hosting | Vercel (Python runtime) | Code lives on GitHub; Vercel deploys on every push to `main` |

Do **not** use the Tailwind Play CDN script in production.

---

## 5. Project structure

Target layout (Claude Code may adjust small details in the plan, but keep the overall shape):

```
pocketly/
├── app/
│   ├── __init__.py          # create_app() factory, registers blueprints
│   ├── config.py            # Config class, reads env vars
│   ├── supabase_client.py   # get_supabase() helper (not used yet)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── main.py          # landing page "/"
│   │   └── placeholders.py  # /login, /signup, /dashboard, /analytics
│   ├── templates/
│   │   ├── base.html        # shared layout
│   │   ├── components/      # reusable partials (navbar, footer, buttons)
│   │   ├── landing.html
│   │   └── coming_soon.html # used by all placeholder routes
│   └── static/
│       ├── css/
│       │   ├── input.css    # Tailwind source (@tailwind directives + custom layers)
│       │   └── output.css   # compiled, committed
│       └── img/             # logo / favicon
├── api/
│   └── index.py             # Vercel entry point, imports the Flask app
├── tailwind.config.js
├── requirements.txt
├── vercel.json
├── .env.example
├── .gitignore
└── README.md
```

---

## 6. Design system

### 6.1 Colors (ratio ≈ 70% cream / 30% black / small accent of orange)

| Token | Hex | Use |
|---|---|---|
| `cream` | `#F4EFE6` | Page backgrounds (dominant) |
| `cream-dark` | `#EAE3D6` | Section dividers, subtle surfaces, borders |
| `ink` | `#141414` | Primary text, black buttons, dark cards |
| `ink-soft` | `#4A4A4A` | Secondary text, subtext |
| `ember` | `#D9541E` | Burnt orange accent: primary CTA, underline swoosh, small highlights only |
| `ember-dark` | `#B84415` | CTA hover state |
| `white` | `#FFFFFF` | Floating cards on cream |

Add these as custom colors in `tailwind.config.js`. Orange must stay an **accent**: never a large background area.

### 6.2 Typography

- **Headings & UI:** a bold geometric sans-serif — **Inter** (or Manrope), weights 400/500/600/800.
- **Accent words:** an italic serif — **Instrument Serif** (italic), used for 1–3 words in headlines only (e.g. "*actually goes.*").
- Load both from Google Fonts in `base.html`.
- Hero headline: very large and tight (≈ 56–72px desktop, ≈ 40px mobile), tight letter-spacing, heavy weight.

### 6.3 Components (Tailwind `@layer components` classes or Jinja macros)

| Component | Style |
|---|---|
| `btn-primary` | Orange (`ember`) background, white text, fully rounded (pill), arrow "→" optional, darker on hover |
| `btn-dark` | `ink` background, white text, pill shape |
| `btn-ghost` | Transparent, `ink` text, no border, underline or soft background on hover |
| `card` | White background, rounded-2xl, soft shadow, padding 16–24px |
| `card-dark` | `ink` background, cream text |
| `underline-swoosh` | Hand-drawn style orange SVG underline placed under an italic accent word |

### 6.4 Layout rules

- Max content width ≈ 1200px, centered, generous horizontal padding.
- Lots of whitespace; minimal borders; rounded corners everywhere.
- Mobile-first and fully responsive (breakpoints: mobile < 640px, tablet, desktop ≥ 1024px).

---

## 7. Base layout (`base.html`)

- HTML5 skeleton, `lang="en"`, responsive viewport meta.
- `<title>` block defaulting to "Pocketly — Know where your pocket money goes".
- Meta description and favicon.
- Loads Google Fonts and `static/css/output.css`.
- Blocks: `title`, `navbar` (default navbar included), `content`, `footer` (default footer included), `scripts`.
- Cream background on `<body>`, `ink` text color.

### Navbar (component)
- Left: Pocketly logo: wordmark "Pocketly" in bold sans with a small orange dot or icon.
- Right: "Log in" (`btn-ghost`, links to `/login`) and "Get started" (`btn-dark`, links to `/signup`).
- Mobile: same two buttons, compact; no hamburger menu needed.

### Footer (component)
- One minimal line: "© 2026 Pocketly · Built in Lahore" (left) and a small tagline or links (right).

---

## 8. Landing page (`/`)

Visual style reference: modern SaaS landing (bold sans headline with italic serif accent word and orange underline, cream background, floating white cards). Keep it **minimal**: a single screen hero plus a short features strip.

### 8.1 Hero section (two columns on desktop, stacked on mobile)

**Left column**
- Small pill badge above headline: "New · Track your pocket money in seconds" (black pill with tiny label).
- Headline: **"Know where your pocket money** *actually goes.*" (the italic part uses the serif font with the orange swoosh underline).
- Subtext (ink-soft, 1–2 lines): "Pocketly lets you log daily expenses in seconds and shows you exactly how this month is going, so you never wonder where it all went."
- Buttons: `btn-primary` "Get started →" (→ `/signup`) and `btn-ghost` "Log in" (→ `/login`).
- Small trust line under buttons: "Free · No card needed · Built for students".

**Right column: hero visual (pure HTML/CSS, no images required)**
- A dark (`card-dark`) or cream-dark rounded panel as background.
- Floating white card on top: **"November"** label, big number **"Rs 6,450"** with small text "spent this month", and a thin progress bar (orange fill) labeled "65% of Rs 10,000".
- Second floating white card, overlapping slightly: a mini list "Today" with 3–4 sample rows, each with a category label, amount and time, e.g.
  - Food — Rs 350 — 1:15 PM
  - Transport — Rs 120 — 9:40 AM
  - Mobile top-up — Rs 500 — 8:05 AM
- Optional tiny bar-chart card (7 small bars, one highlighted in `ember`) labeled "This week".
- Sample data is static placeholder content in the template.

### 8.2 Features strip (3 items, below hero)

Three short columns, each with a small icon (inline SVG), a bold title and one line of text:
1. **Add in seconds**: "Tap +, type the amount, done."
2. **This month at a glance**: "Your home screen shows only what you spent this month."
3. **Understand your spending**: "Simple analytics show where your money goes."

### 8.3 Final CTA (optional, small)
A short centered line "Ready to take control of your pocket money?" with `btn-primary` "Get started →".

### 8.4 Footer
Shared footer component.

---

## 9. Placeholder routes

All render `coming_soon.html` (which extends `base.html`) with a page-specific title and one line of text, plus a "← Back to home" link.

| Route | Heading |
|---|---|
| `/login` | Log in |
| `/signup` | Create your account |
| `/dashboard` | Your month |
| `/analytics` | Analytics |

These will be replaced by real pages in later specs; keep them in a separate blueprint (`placeholders.py`) so they're easy to remove.

Also add a simple styled **404 page** that extends `base.html`.

---

## 10. Configuration & Supabase setup

- `config.py` reads from environment variables: `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `FLASK_ENV`.
- Use `python-dotenv` to load `.env` locally.
- `.env.example` lists every variable with empty values; `.env` is git-ignored.
- `supabase_client.py` exposes `get_supabase()` that creates the client lazily from config. It must **not** crash the app if keys are missing during Part 1 (log a warning instead).
- No Supabase calls are made anywhere in Part 1.

---

## 11. Deployment (Vercel)

- `api/index.py` imports the app from `create_app()` and exposes it as `app` for Vercel's Python runtime.
- `vercel.json` routes all requests to the Flask app and serves `/static/*` correctly.
- `requirements.txt` pins versions for: `flask`, `supabase`, `python-dotenv` (plus anything else the plan needs).
- Environment variables are set in the Vercel project settings (documented in README).
- Compiled `output.css` is committed, so no build command is required on Vercel.

## 12. README

Must include:
1. What Pocketly is (1–2 lines).
2. Local setup: create venv, install requirements, copy `.env.example` → `.env`, run `flask run`.
3. How to rebuild Tailwind CSS (standalone CLI command, plus a `--watch` command for development).
4. How to deploy: push to GitHub, import repo in Vercel, add env vars.

---

## 13. Acceptance criteria

Part 1 is done when **all** of these are true:

**Structure & setup**
- [ ] Project matches the structure in section 5 (minor deviations explained in the plan).
- [ ] App uses `create_app()` and Blueprints.
- [ ] `flask run` starts with no errors, even with empty Supabase keys.

**Design**
- [ ] Colors, fonts and components from section 6 are defined in Tailwind config / CSS and used consistently.
- [ ] The page is visually ~70% cream, ~30% black, with orange used only as an accent.
- [ ] Headline uses the italic serif accent word with an orange underline swoosh.

**Landing page**
- [ ] Navbar, hero (both columns), features strip and footer are present as described in section 8.
- [ ] "Get started" buttons go to `/signup`; "Log in" buttons go to `/login`.
- [ ] Layout is responsive: no horizontal scrolling and readable on a 375px-wide phone; hero stacks vertically on mobile.

**Routes**
- [ ] `/login`, `/signup`, `/dashboard`, `/analytics` show styled "coming soon" pages with a link back home.
- [ ] Unknown URLs show the styled 404 page.

**Deployment**
- [ ] `.env` is git-ignored; `.env.example` exists.
- [ ] Repo is on GitHub and the app is live on a Vercel URL with styles and fonts loading correctly.
- [ ] README covers local run, Tailwind rebuild and deployment.

---

## 14. Notes for Claude Code (plan mode)

- Produce a plan listing every file to create, in order, before writing code.
- Keep templates small and reusable (navbar/footer/buttons as partials or macros); later specs will add many pages.
- Don't add authentication, database tables or JavaScript frameworks in this part.
- If anything in this spec conflicts with how Vercel's Python runtime works, follow Vercel's current documented approach and note the change in the plan.
