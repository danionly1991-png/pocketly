"""App configuration, read from environment variables.

Locally, values come from a `.env` file (loaded by python-dotenv).
On Vercel, they come from the project's Environment Variables settings.
"""

import logging
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    logger.warning(
        "SECRET_KEY is not set; using a random per-process key. "
        "Sessions and login are live, so set SECRET_KEY or users will be logged out on every restart."
    )
    return secrets.token_hex(32)


def _site_url() -> str:
    url = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if not url:
        logger.warning("SITE_URL is not set; links in verification and reset emails will not work.")
    return url


_SITE_URL = _site_url()


class Config:
    # App-level environment flag ("development" or "production").
    # Note: Flask itself no longer reads FLASK_ENV; use FLASK_DEBUG=1 for the debugger.
    FLASK_ENV = os.environ.get("FLASK_ENV", "").strip() or "production"
    DEBUG = FLASK_ENV == "development"

    SECRET_KEY = _secret_key()

    SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()

    # Public base URL of the app, used for the links in auth emails.
    SITE_URL = _SITE_URL

    # Session cookie. Secure only when the site really runs on https, so local
    # http logins keep working while Vercel always gets a Secure cookie.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _SITE_URL.startswith("https://")
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # The CSRF token lives as long as the session cookie, so open forms don't expire.
    WTF_CSRF_TIME_LIMIT = None
