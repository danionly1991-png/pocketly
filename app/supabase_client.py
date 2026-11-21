"""Per-request Supabase client helper.

`get_supabase()` builds a new client for each request and keeps it on `flask.g`,
so helpers in the same request share it but it never outlives the request.
There is deliberately no module-level client: a supabase client keeps the
logged-in session in its own memory, and on a warm serverless instance a shared
client could leak one user's session into another user's request.

The client is stateless on purpose:
- `flow_type="implicit"`: our email links use `token_hash` + `verify_otp`, which
  needs no PKCE code verifier (a verifier would be lost between requests).
- `persist_session=False` and `auto_refresh_token=False`: no storage and no
  background timer threads. Tokens live in Flask's cookie session and are
  refreshed by `app.auth_utils.load_current_user`.

If the keys are missing, a warning is logged and `None` is returned so the app
keeps running. Callers must handle `None`.

There are two per-request clients:
- `get_supabase()`: anon key only, used for Supabase Auth (sign in, refresh, ...).
- `get_user_supabase(token)`: anon key plus the logged-in user's access token in the
  `Authorization` header, used for tables, RPC and Storage so Row Level Security
  applies as that user. The service_role key is never used.
"""

from flask import current_app, g


def supabase_configured() -> bool:
    return bool(current_app.config.get("SUPABASE_URL") and current_app.config.get("SUPABASE_ANON_KEY"))


def get_supabase():
    client = g.get("_supabase")
    if client is not None:
        return client

    if not supabase_configured():
        current_app.logger.warning("Supabase is not configured (SUPABASE_URL / SUPABASE_ANON_KEY missing).")
        return None

    # Imported lazily so the package is only loaded when actually needed (faster cold starts).
    from supabase import ClientOptions, create_client

    g._supabase = create_client(
        current_app.config["SUPABASE_URL"],
        current_app.config["SUPABASE_ANON_KEY"],
        options=ClientOptions(flow_type="implicit", persist_session=False, auto_refresh_token=False),
    )
    return g._supabase


def get_user_supabase(access_token: str | None):
    """Client that sends the user's JWT, so RLS applies as that user. None if unavailable.

    The caller passes the token (this module must not import `auth_utils`: import cycle).
    """
    if not access_token:
        return None

    client = g.get("_supabase_user")
    if client is not None:
        return client

    if not supabase_configured():
        current_app.logger.warning("Supabase is not configured (SUPABASE_URL / SUPABASE_ANON_KEY missing).")
        return None

    from supabase import ClientOptions, create_client

    g._supabase_user = create_client(
        current_app.config["SUPABASE_URL"],
        current_app.config["SUPABASE_ANON_KEY"],
        options=ClientOptions(
            headers={"Authorization": f"Bearer {access_token}"},
            flow_type="implicit",
            persist_session=False,
            auto_refresh_token=False,
        ),
    )
    return g._supabase_user
