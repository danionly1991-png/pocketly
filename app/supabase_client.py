"""Lazy Supabase client helper.

Not used in Part 1. Later specs call `get_supabase()` inside a request or
app context. The client is created once on first use. If the keys are
missing, a warning is logged and `None` is returned so the app keeps running.
"""

from flask import current_app

_client = None


def supabase_configured() -> bool:
    return bool(current_app.config.get("SUPABASE_URL") and current_app.config.get("SUPABASE_ANON_KEY"))


def get_supabase():
    global _client
    if _client is not None:
        return _client

    if not supabase_configured():
        current_app.logger.warning("Supabase is not configured (SUPABASE_URL / SUPABASE_ANON_KEY missing).")
        return None

    # Imported lazily so the package is only loaded when actually needed (faster cold starts).
    from supabase import create_client

    _client = create_client(current_app.config["SUPABASE_URL"], current_app.config["SUPABASE_ANON_KEY"])
    return _client
