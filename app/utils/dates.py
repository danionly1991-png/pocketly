"""Karachi time, month/day helpers and the Jinja formatting filters.

All "today" and "current month" logic goes through `karachi_today()`: Vercel runs in UTC,
so the server's local date is wrong for Pakistan between 19:00 and 24:00 UTC.
Money is always `Decimal`, never `float`.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Flask

KARACHI = ZoneInfo("Asia/Karachi")
EARLIEST_MONTH = date(2000, 1, 1)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Time -------------------------------------------------------------------


def karachi_today() -> date:
    return datetime.now(KARACHI).date()


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(first: date) -> date:
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def shift_month(first: date, months: int) -> date:
    index = first.year * 12 + (first.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


# --- Query-string / form parsing --------------------------------------------


def parse_month_param(value: str | None, current_month: date) -> date | None:
    """`YYYY-MM` -> first day of that month, or None if bad, too old or in the future."""
    if not value or not _MONTH_RE.match(value):
        return None
    month = date(int(value[:4]), int(value[5:7]), 1)
    if month < EARLIEST_MONTH or month > current_month:
        return None
    return month


def parse_day_param(value: str | None, month: date, today: date) -> date | None:
    """`YYYY-MM-DD` inside `month` and not after today, else None."""
    day = parse_iso_date(value)
    if day is None or day > today:
        return None
    if (day.year, day.month) != (month.year, month.month):
        return None
    return day


def parse_iso_date(value: str | None) -> date | None:
    if not value or not _DAY_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def month_options(first_month: date, current_month: date) -> list[tuple[str, str]]:
    """Newest first: [("2026-11", "November 2026"), ...] from the current month back to `first_month`."""
    first_month = min(month_start(first_month), current_month)
    options: list[tuple[str, str]] = []
    month = current_month
    while month >= first_month:
        options.append((f"{month:%Y-%m}", month_label(month)))
        month = shift_month(month, -1)
    return options


def to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


# --- Jinja filters ----------------------------------------------------------


def money(value) -> str:
    """Rs 1,250 for whole amounts, Rs 99.50 when there are paise."""
    amount = to_decimal(value).quantize(Decimal("0.01"))
    if amount == amount.to_integral_value():
        return f"Rs {int(amount):,}"
    return f"Rs {amount:,.2f}"


def amount_input(value) -> str:
    """Value for an <input>: 1250 or 99.50 (no thousands separators)."""
    amount = to_decimal(value).quantize(Decimal("0.01"))
    if amount == amount.to_integral_value():
        return str(int(amount))
    return f"{amount:.2f}"


def short_date(d: date) -> str:
    return f"{d:%a}, {d.day} {d:%b}"


def long_date(d: date) -> str:
    return f"{d:%A}, {d.day} {d:%B %Y}"


def month_label(d: date) -> str:
    return f"{d:%B %Y}"


def month_name(d: date) -> str:
    return f"{d:%B}"


def day_month(d: date) -> str:
    return f"{d.day} {d:%b}"


def day_name(d: date) -> str:
    return f"{d:%A}"


def iso_day_name(value: str | None) -> str:
    """Weekday for an ISO date string ("Saturday"), or "" if it isn't a valid date."""
    parsed = parse_iso_date(value)
    return day_name(parsed) if parsed else ""


def register_filters(app: Flask) -> None:
    for fn in (money, amount_input, short_date, long_date, month_label, month_name, day_month, day_name, iso_day_name):
        app.add_template_filter(fn, fn.__name__)
