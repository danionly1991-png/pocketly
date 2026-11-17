"""Supabase Auth calls. This is the only module that talks to Supabase Auth.

Routes call these functions and never see raw Supabase errors: every failure is
turned into an `AuthError` with a friendly `user_message`. Only the error code
and HTTP status are logged, never request bodies or passwords.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass

import httpx
from flask import current_app
from supabase_auth.errors import AuthWeakPasswordError
from supabase_auth.errors import AuthError as SupabaseAuthError

from app.supabase_client import get_supabase

logger = logging.getLogger(__name__)

GENERIC_MESSAGE = "Something went wrong. Please try again."
UNAVAILABLE_MESSAGE = "Login isn't available right now. Please try again later."
RATE_LIMIT_MESSAGE = "Please wait a minute before trying again."
WEAK_PASSWORD_MESSAGE = "Password must be at least 8 characters and include a letter and a number."

# Codes that mean "this email link is no longer usable".
_LINK_CODES = {"otp_expired", "otp_invalid", "otp_disabled", "flow_state_expired", "flow_state_not_found"}
_RATE_LIMIT_CODES = {"over_email_send_rate_limit", "over_request_rate_limit", "over_sms_send_rate_limit"}

_MESSAGES = {
    "invalid_credentials": "Incorrect email or password.",
    "email_not_confirmed": "Please verify your email first.",
    "same_password": "Your new password must be different from the old one.",
}


class AuthError(Exception):
    """A failed auth operation, carrying text that is safe to show to the user."""

    def __init__(self, user_message: str, code: str | None = None, field: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.field = field


@dataclass(frozen=True)
class SessionData:
    """What we keep in the cookie session. Deliberately small (cookie limit is ~4 KB)."""

    access_token: str
    refresh_token: str
    expires_at: int
    user_id: str
    email: str
    name: str

    def to_dict(self) -> dict:
        return asdict(self)


def _to_session_data(session) -> SessionData:
    user = session.user
    metadata = user.user_metadata or {}
    email = user.email or ""
    name = (metadata.get("full_name") or "").strip() or email.split("@")[0]
    expires_at = session.expires_at or int(time.time()) + int(session.expires_in or 3600)
    return SessionData(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_at=int(expires_at),
        user_id=str(user.id),
        email=email,
        name=name,
    )


def _client():
    client = get_supabase()
    if client is None:
        raise AuthError(UNAVAILABLE_MESSAGE, code="unavailable")
    return client.auth


def _friendly(error: Exception) -> AuthError:
    """Translate any Supabase / network error into an AuthError."""
    if isinstance(error, SupabaseAuthError):
        code = getattr(error, "code", None)
        status = getattr(error, "status", None)
        logger.warning("Supabase auth error: code=%s status=%s", code, status)

        if isinstance(error, AuthWeakPasswordError) or code == "weak_password":
            return AuthError(WEAK_PASSWORD_MESSAGE, code="weak_password", field="password")
        if code in _RATE_LIMIT_CODES or status == 429:
            return AuthError(RATE_LIMIT_MESSAGE, code="rate_limit")
        if code in _MESSAGES:
            field = "password" if code == "same_password" else None
            return AuthError(_MESSAGES[code], code=code, field=field)
        return AuthError(GENERIC_MESSAGE, code=code or "unknown")

    # Network problems, timeouts and anything unexpected.
    logger.warning("Auth request failed: %s", type(error).__name__)
    return AuthError(GENERIC_MESSAGE, code="unknown")


def _link_error(error: Exception) -> AuthError:
    """Like _friendly, but a dead email link becomes code='link_invalid'."""
    code = getattr(error, "code", None)
    status = getattr(error, "status", None)
    if isinstance(error, SupabaseAuthError) and (code in _LINK_CODES or status in (400, 403, 404, 422)):
        logger.warning("Email link rejected: code=%s status=%s", code, status)
        return AuthError("This link is invalid or has expired.", code="link_invalid")
    return _friendly(error)


_CAUGHT = (SupabaseAuthError, httpx.HTTPError, OSError, ValueError)


def sign_up(email: str, password: str, name: str) -> None:
    """Create an account. Supabase does not reveal whether the email already exists."""
    auth = _client()
    try:
        auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {"full_name": name},
                    "email_redirect_to": current_app.config["SITE_URL"] + "/auth/confirm",
                },
            }
        )
    except _CAUGHT as error:
        raise _friendly(error) from None


def resend_verification(email: str) -> None:
    auth = _client()
    try:
        auth.resend(
            {
                "type": "signup",
                "email": email,
                "options": {"email_redirect_to": current_app.config["SITE_URL"] + "/auth/confirm"},
            }
        )
    except _CAUGHT as error:
        raise _friendly(error) from None


def sign_in(email: str, password: str) -> SessionData:
    auth = _client()
    try:
        response = auth.sign_in_with_password({"email": email, "password": password})
    except _CAUGHT as error:
        raise _friendly(error) from None
    if not response.session:
        raise AuthError(GENERIC_MESSAGE, code="no_session")
    return _to_session_data(response.session)


def verify_link(token_hash: str, link_type: str) -> SessionData:
    """Verify a token_hash from an email link. link_type: 'email' or 'recovery'."""
    auth = _client()
    try:
        response = auth.verify_otp({"token_hash": token_hash, "type": link_type})
    except _CAUGHT as error:
        raise _link_error(error) from None
    if not response.session:
        raise AuthError("This link is invalid or has expired.", code="link_invalid")
    return _to_session_data(response.session)


def sign_out(access_token: str) -> None:
    """Revoke this device's session. Uses the user's own JWT (no service_role key)."""
    auth = _client()
    try:
        auth.admin.sign_out(access_token, "local")
    except _CAUGHT as error:
        raise _friendly(error) from None


def send_reset(email: str) -> None:
    """Send a password reset email. Unknown emails don't raise an error."""
    auth = _client()
    try:
        auth.reset_password_for_email(email, {"redirect_to": current_app.config["SITE_URL"] + "/auth/confirm"})
    except _CAUGHT as error:
        raise _friendly(error) from None


def update_password(access_token: str, refresh_token: str, new_password: str) -> SessionData:
    """Set a new password for the user identified by the given tokens.

    `update_user` reads the session stored in the client, so we load it first
    (this also validates or refreshes the token).
    """
    auth = _client()
    try:
        auth.set_session(access_token, refresh_token)
        auth.update_user({"password": new_password})
        session = auth.get_session()
    except _CAUGHT as error:
        raise _friendly(error) from None
    if session is None:
        raise AuthError(GENERIC_MESSAGE, code="no_session")
    return _to_session_data(session)


def refresh(refresh_token: str) -> SessionData:
    auth = _client()
    try:
        response = auth.refresh_session(refresh_token)
    except _CAUGHT as error:
        raise _friendly(error) from None
    if not response.session:
        raise AuthError(GENERIC_MESSAGE, code="no_session")
    return _to_session_data(response.session)
