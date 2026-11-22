"""Expense queries and the dashboard view. Runs as the logged-in user, so RLS applies.

Money is `Decimal`: amounts are read with `amount::text` and totals come from the
`dashboard_totals` SQL function (a database `sum()`), never from adding floats in Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from postgrest.exceptions import APIError

from app.services.categories import Category, to_category
from app.services.db import CAUGHT, CATEGORY_MESSAGE, DataError, friendly, user_client
from app.utils.dates import (
    adjacent_months,
    karachi_today,
    month_end,
    month_options,
    month_start,
    parse_day_param,
    parse_month_param,
    to_decimal,
)

CATEGORY_COLUMNS = "id,name,icon_type,icon_value,is_default,is_fallback"
COLUMNS = f"id,amount::text,spent_on,note,created_at,category:categories({CATEGORY_COLUMNS})"


@dataclass(frozen=True)
class Expense:
    id: str
    amount: Decimal
    spent_on: date
    note: str | None
    category: Category


@dataclass(frozen=True)
class Totals:
    first_month: date
    month_to_date: Decimal  # current month, day 1 .. today (the "Spent this month" tab)
    view_total: Decimal  # the viewed month, or the selected day


@dataclass(frozen=True)
class DashboardView:
    today: date
    current_month: date
    first_month: date  # earliest month the Month selector offers
    month: date
    day: date | None
    is_current_month: bool
    month_options: list[tuple[str, str]]
    expenses: list[Expense]
    totals: Totals
    date_min: date  # day picker limits
    date_max: date

    @property
    def month_value(self) -> str:
        """The `?month=` value for this view, e.g. "2026-11"."""
        return f"{self.month:%Y-%m}"

    @property
    def prev_month(self) -> date | None:
        """Target of the ‹ arrow, or None at the first available month."""
        return adjacent_months(self.month, self.first_month, self.current_month)[0]

    @property
    def next_month(self) -> date | None:
        """Target of the › arrow, or None on the current month."""
        return adjacent_months(self.month, self.first_month, self.current_month)[1]

    @property
    def day_value(self) -> str:
        return self.day.isoformat() if self.day else ""


def _to_expense(row: dict) -> Expense:
    return Expense(
        id=row["id"],
        amount=Decimal(row["amount"]),
        spent_on=date.fromisoformat(row["spent_on"]),
        note=row.get("note"),
        category=to_category(row["category"]),
    )


def _write_error(error: Exception) -> DataError:
    if isinstance(error, APIError) and error.code in ("42501", "23503"):
        return DataError(CATEGORY_MESSAGE, code="category", field="category_id")
    return friendly(error)


def list_expenses(start: date, end: date) -> list[Expense]:
    """Expenses from `start` to `end` inclusive, newest first."""
    try:
        rows = (
            user_client()
            .table("expenses")
            .select(COLUMNS)
            .gte("spent_on", start.isoformat())
            .lte("spent_on", end.isoformat())
            .order("spent_on", desc=True)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    except CAUGHT as error:
        raise friendly(error) from None
    return [_to_expense(row) for row in rows]


def get_expense(expense_id: str) -> Expense | None:
    try:
        response = user_client().table("expenses").select(COLUMNS).eq("id", expense_id).maybe_single().execute()
    except CAUGHT as error:
        raise friendly(error) from None
    return _to_expense(response.data) if response and response.data else None


def create_expense(category_id: str, amount: Decimal, spent_on: date, note: str | None) -> dict:
    try:
        rows = (
            user_client()
            .table("expenses")
            .insert(
                {"category_id": category_id, "amount": str(amount), "spent_on": spent_on.isoformat(), "note": note}
            )
            .execute()
            .data
        )
    except CAUGHT as error:
        raise _write_error(error) from None
    return {"id": rows[0]["id"], "spent_on": date.fromisoformat(rows[0]["spent_on"])}


def update_expense(expense_id: str, category_id: str, amount: Decimal, spent_on: date, note: str | None) -> bool:
    """True if the expense was updated, False if it doesn't exist (or isn't the user's)."""
    try:
        rows = (
            user_client()
            .table("expenses")
            .update(
                {"category_id": category_id, "amount": str(amount), "spent_on": spent_on.isoformat(), "note": note}
            )
            .eq("id", expense_id)
            .execute()
            .data
        )
    except CAUGHT as error:
        raise _write_error(error) from None
    return bool(rows)


def delete_expense(expense_id: str) -> date | None:
    """Delete an expense and return its date, or None if it doesn't exist."""
    try:
        rows = user_client().table("expenses").delete().eq("id", expense_id).execute().data
    except CAUGHT as error:
        raise friendly(error) from None
    return date.fromisoformat(rows[0]["spent_on"]) if rows else None


def dashboard_totals(today: date, view_from: date, view_to: date) -> Totals:
    try:
        rows = (
            user_client()
            .rpc(
                "dashboard_totals",
                {
                    "p_today": today.isoformat(),
                    "p_view_from": view_from.isoformat(),
                    "p_view_to": view_to.isoformat(),
                },
            )
            .execute()
            .data
        )
    except CAUGHT as error:
        raise friendly(error) from None
    row = rows[0] if isinstance(rows, list) else rows
    return Totals(
        first_month=date.fromisoformat(row["first_month"]),
        month_to_date=to_decimal(row["month_to_date_total"]),
        view_total=to_decimal(row["view_total"]),
    )


def build_dashboard(month_param: str | None, day_param: str | None) -> DashboardView:
    """Everything the dashboard page needs. Invalid month/day params are silently ignored."""
    today = karachi_today()
    current = month_start(today)
    month = parse_month_param(month_param, current) or current
    day = parse_day_param(day_param, month, today)
    is_current = month == current

    view_from, view_to = (day, day) if day else (month, month_end(month))
    expenses = list_expenses(view_from, view_to)
    totals = dashboard_totals(today, view_from, view_to)
    first_month = min(month_start(totals.first_month), month)

    return DashboardView(
        today=today,
        current_month=current,
        first_month=first_month,
        month=month,
        day=day,
        is_current_month=is_current,
        month_options=month_options(first_month, current),
        expenses=expenses,
        totals=totals,
        date_min=month,
        date_max=today if is_current else month_end(month),
    )


def empty_view(month_param: str | None, day_param: str | None) -> DashboardView:
    """The dashboard with no data, for when the database can't be reached (no network calls)."""
    today = karachi_today()
    current = month_start(today)
    month = parse_month_param(month_param, current) or current
    day = parse_day_param(day_param, month, today)
    is_current = month == current
    zero = Decimal("0")
    return DashboardView(
        today=today,
        current_month=current,
        first_month=month,
        month=month,
        day=day,
        is_current_month=is_current,
        month_options=month_options(month, current),
        expenses=[],
        totals=Totals(first_month=month, month_to_date=zero, view_total=zero),
        date_min=month,
        date_max=today if is_current else month_end(month),
    )
