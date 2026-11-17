"""App configuration, read from environment variables.

Locally, values come from a `.env` file (loaded by python-dotenv).
On Vercel, they come from the project's Environment Variables settings.
"""

import logging
import os
import secrets

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    logger.warning(
        "SECRET_KEY is not set; using a random per-process key. "
        "Set SECRET_KEY before sessions are used (Spec 02)."
    )
    return secrets.token_hex(32)


class Config:
    # App-level environment flag ("development" or "production").
    # Note: Flask itself no longer reads FLASK_ENV; use FLASK_DEBUG=1 for the debugger.
    FLASK_ENV = os.environ.get("FLASK_ENV", "").strip() or "production"
    DEBUG = FLASK_ENV == "development"

    SECRET_KEY = _secret_key()

    SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
