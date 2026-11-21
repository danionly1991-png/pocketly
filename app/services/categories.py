"""Category queries. Runs as the logged-in user, so RLS only ever returns their own rows.

There is deliberately no limit on how many categories a user can create.
"""

from __future__ import annotations

from dataclasses import dataclass

from postgrest.exceptions import APIError

from app.services import storage
from app.services.db import CAUGHT, GENERIC_MESSAGE, DataError, friendly, user_client

COLUMNS = "id,name,icon_type,icon_value,is_default,is_fallback"
DUPLICATE_MESSAGE = "You already have a category with this name."


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    icon_type: str  # "emoji" | "image"
    icon_value: str  # the emoji, or the Storage object path
    is_default: bool
    is_fallback: bool
    icon_url: str | None  # public URL for image icons, else None


def to_category(row: dict) -> Category:
    icon_url = storage.icon_url(row["icon_value"]) if row["icon_type"] == "image" else None
    return Category(
        id=row["id"],
        name=row["name"],
        icon_type=row["icon_type"],
        icon_value=row["icon_value"],
        is_default=row["is_default"],
        is_fallback=row["is_fallback"],
        icon_url=icon_url,
    )


def _translate(error: Exception) -> DataError:
    if isinstance(error, APIError) and error.code == "23505":
        return DataError(DUPLICATE_MESSAGE, code="duplicate", field="name")
    return friendly(error)


def list_categories() -> list[Category]:
    """All of the user's categories: fallback ("Other") last, then oldest first."""
    try:
        rows = (
            user_client()
            .table("categories")
            .select(COLUMNS)
            .order("is_fallback")
            .order("created_at")
            .order("name")
            .execute()
            .data
        )
    except CAUGHT as error:
        raise friendly(error) from None
    return [to_category(row) for row in rows]


def get_category(category_id: str) -> Category | None:
    try:
        response = user_client().table("categories").select(COLUMNS).eq("id", category_id).maybe_single().execute()
    except CAUGHT as error:
        raise friendly(error) from None
    return to_category(response.data) if response and response.data else None


def expense_counts() -> dict[str, int]:
    """Number of expenses per category id (categories with none are absent)."""
    try:
        rows = user_client().rpc("category_expense_counts").execute().data
    except CAUGHT as error:
        raise friendly(error) from None
    return {row["category_id"]: int(row["expense_count"]) for row in rows}


def create_category(name: str, icon_type: str, icon_value: str) -> Category:
    try:
        rows = (
            user_client()
            .table("categories")
            .insert({"name": name, "icon_type": icon_type, "icon_value": icon_value})
            .execute()
            .data
        )
    except CAUGHT as error:
        raise _translate(error) from None
    return to_category(rows[0])


def update_category(category_id: str, name: str, icon_type: str, icon_value: str) -> Category | None:
    try:
        rows = (
            user_client()
            .table("categories")
            .update({"name": name, "icon_type": icon_type, "icon_value": icon_value})
            .eq("id", category_id)
            .execute()
            .data
        )
    except CAUGHT as error:
        raise _translate(error) from None
    return to_category(rows[0]) if rows else None


def delete_category(category_id: str) -> int:
    """Move the category's expenses to the user's fallback ("Other"), delete it, return the moved count."""
    try:
        moved = user_client().rpc("delete_category", {"p_category_id": category_id}).execute().data
    except APIError as error:
        if error.message == "category_not_found":
            raise DataError(GENERIC_MESSAGE, code="not_found") from None
        if error.message == "cannot_delete_fallback":
            raise DataError("This category can't be deleted.", code="fallback") from None
        raise friendly(error) from None
    except CAUGHT as error:
        raise friendly(error) from None
    return int(moved or 0)
