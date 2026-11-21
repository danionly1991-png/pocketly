"""Login session helpers: reusable by every feature that needs a logged-in user.

The login lives only in Flask's signed cookie session (no server-side state):
    session["auth"]          -> SessionData dict (tokens + id, email, name)
    session["recovery"]      -> tokens from a password-reset link (not a login yet)
    session["pending_email"] -> address shown on /check-email and used for resend
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import wraps
from urllib.parse import urlsplit

from flask import flash, g, redirect, request, session, url_for

from app.services import auth_service

# Refresh the access token when it expires within this many seconds.
REFRESH_MARGIN = 60


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: str

    @property
    def initial(self) -> str:
        """First letter for the profile circle."""
        return (self.name or self.email or "?")[:1].upper()


def save_login(data: auth_service.SessionData) -> None:
    """Start a fresh session for this user. Clearing first prevents session fixation."""
    session.clear()
    session["auth"] = data.to_dict()
    session.permanent = True


def clear_login() -> None:
    session.clear()


def load_current_user() -> None:
    """before_request hook: read the user from the cookie, refreshing tokens if needed."""
    g.current_user = None
    g.session_expired = False

    if request.endpoint == "static":
        return

    data = session.get("auth")
    if not data:
        return

    try:
        expires_at = int(data["expires_at"])
        user = CurrentUser(id=data["user_id"], email=data["email"], name=data["name"])
        refresh_token = data["refresh_token"]
    except (KeyError, TypeError, ValueError):
        clear_login()
        return

    if expires_at - REFRESH_MARGIN <= time.time():
        try:
            fresh = auth_service.refresh(refresh_token)
        except auth_service.AuthError:
            clear_login()
            g.session_expired = True
            return
        session["auth"] = fresh.to_dict()
        session.permanent = True
        user = CurrentUser(id=fresh.user_id, email=fresh.email, name=fresh.name)

    g.current_user = user


def current_user() -> CurrentUser | None:
    return g.get("current_user")


def access_token() -> str | None:
    data = session.get("auth")
    return data.get("access_token") if data else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "error")
            target = request.full_path.rstrip("?")
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)

    return wrapped


def logged_out_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is not None:
            return redirect(url_for("expenses.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def safe_next(target: str | None) -> str | None:
    """Return `target` only if it is a plain internal path, otherwise None."""
    if not target or not target.startswith("/"):
        return None
    if target.startswith("//") or "\\" in target:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    return target
