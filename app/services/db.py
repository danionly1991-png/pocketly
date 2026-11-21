"""Shared plumbing for the data services (expenses, categories, storage).

Services call `user_client()` to get a Supabase client that carries the logged-in
user's access token, so Row Level Security applies as that user. Every failure is
turned into a `DataError` with a message that is safe to show: raw Supabase errors,
tracebacks and row data are never shown or logged.
"""

from __future__ import annotations

import logging

import httpx
from postgrest.exceptions import APIError
from storage3.utils import StorageException

from app import auth_utils
from app.supabase_client import get_user_supabase

logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "Pocketly can't reach its database right now. Please try again in a moment."
GENERIC_MESSAGE = "Something went wrong. Please try again."
CATEGORY_MESSAGE = "Please choose a category."

# Errors the data services catch and translate.
CAUGHT = (APIError, StorageException, httpx.HTTPError, OSError)


class DataError(Exception):
    """A failed data operation, carrying text that is safe to show to the user."""

    def __init__(self, user_message: str, code: str | None = None, field: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.field = field


def user_client():
    client = get_user_supabase(auth_utils.access_token())
    if client is None:
        raise DataError(UNAVAILABLE_MESSAGE, code="unavailable")
    return client


def friendly(error: Exception) -> DataError:
    """Translate any Supabase / network error into a DataError. Logs the type and code only."""
    code = getattr(error, "code", None)
    logger.warning("Data request failed: %s code=%s", type(error).__name__, code)

    if isinstance(error, APIError):
        if code == "23505":
            return DataError(GENERIC_MESSAGE, code="duplicate")
        if code in ("42501", "23503"):
            return DataError(GENERIC_MESSAGE, code="forbidden")
        return DataError(GENERIC_MESSAGE, code=code or "unknown")
    return DataError(GENERIC_MESSAGE, code="unknown")
