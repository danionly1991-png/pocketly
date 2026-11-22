"""Karachi time, month/day helpers and the Jinja formatting filters.

All "today" and "current month" logic goes through `karachi_today()`: Vercel runs in UTC,
so the server's local date is wrong for Pakistan between 19:00 and 24:00 UTC.
Money is always `Decimal`, never `float`.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
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


def adjacent_months(month: date, first_month: date, current_month: date) -> tuple[date | None, date | None]:
    """(previous, next) month for the ‹ › arrows, or None where the arrow is disabled."""
    prev = shift_month(month, -1) if month > month_start(first_month) else None
    nxt = shift_month(month, 1) if month < current_month else None
    return prev, nxt


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


def resolve_month_and_day(month_param: str | None, day_param: str | None, today: date) -> tuple[date, date | None]:
    """The dashboard's (month, day). A valid `month` wins and `day` must sit inside it.
    With no valid `month`, a valid past `day` brings its own month, so the calendar button can jump months."""
    current = month_start(today)
    month = parse_month_param(month_param, current)
    if month is not None:
        return month, parse_day_param(day_param, month, today)
    day = parse_iso_date(day_param)
    if day is not None and EARLIEST_MONTH <= day <= today:
        return month_start(day), day
    return current, None


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


def month_from_value(value: str) -> date:
    """"2026-11" -> date(2026, 11, 1). The value must already be valid (e.g. from the database)."""
    return date(int(value[:4]), int(value[5:7]), 1)


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


def money_number(value, whole: bool = False) -> str:
    """The number part of money() (or whole_money()): 1,250 or 99.50. The `amount` macro sets "Rs" separately."""
    return (whole_money(value) if whole else money(value)).removeprefix("Rs ")


def whole_money(value) -> str:
    """Rs 293 for 293.18: rounded half-up to whole rupees (the analytics daily average)."""
    return money(to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


def month_short(d: date) -> str:
    return f"{d:%b}"


def month_value(d: date) -> str:
    """The `?month=` value, e.g. "2026-11"."""
    return f"{d:%Y-%m}"


def day_range_label(start: date, end: date) -> str:
    """"1–22 Oct", or "1 Oct" for a single day (same month)."""
    if start == end:
        return day_month(start)
    return f"{start.day}–{end.day} {end:%b}"


def day_heading(d: date) -> str:
    """Dashboard day-group heading: "Today", "Yesterday", or "Thu, 19 Nov" (Karachi time)."""
    today = karachi_today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return short_date(d)


def day_month(d: date) -> str:
    return f"{d.day} {d:%b}"


def day_name(d: date) -> str:
    return f"{d:%A}"


def iso_day_name(value: str | None) -> str:
    """Weekday for an ISO date string ("Saturday"), or "" if it isn't a valid date."""
    parsed = parse_iso_date(value)
    return day_name(parsed) if parsed else ""


def register_filters(app: Flask) -> None:
    for fn in (
        money,
        money_number,
        whole_money,
        amount_input,
        short_date,
        long_date,
        month_label,
        month_name,
        month_short,
        month_value,
        day_range_label,
        day_heading,
        day_month,
        day_name,
        iso_day_name,
    ):
        app.add_template_filter(fn, fn.__name__)
