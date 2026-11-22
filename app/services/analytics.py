"""Analytics page data (Spec 04). Runs as the logged-in user, so RLS applies.

One RPC call (`get_month_analytics`) returns everything. Every sum is done in SQL, and
money arrives as text, so it becomes an exact `Decimal` here. Python only divides
(percentages), compares and formats. It never adds amounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from flask import url_for

from app.services import storage
from app.services.db import CAUGHT, friendly, user_client
from app.utils.dates import (
    adjacent_months,
    day_range_label,
    karachi_today,
    month_from_value,
    month_label,
    month_name,
    month_options,
    month_short,
    month_start,
    month_value,
    money,
    parse_iso_date,
    parse_month_param,
    short_date,
    shift_month,
    to_decimal,
)

DONUT_SLICES = 6  # the donut shows the top 6 categories plus "Everything else" (grouped in analytics.js)
ZERO = Decimal("0")


@dataclass(frozen=True)
class Icon:
    """What components/category_icon.html needs."""

    icon_type: str
    icon_value: str
    icon_url: str | None


@dataclass(frozen=True)
class CategoryShare:
    id: str
    name: str
    icon: Icon
    total: Decimal
    count: int
    pct: int  # whole percent of the month total, half-up
    in_rest: bool  # drawn inside the donut's "Everything else" slice

    @property
    def pct_label(self) -> str:
        return "<1%" if self.pct == 0 and self.total > 0 else f"{self.pct}%"


@dataclass(frozen=True)
class DayPoint:
    day: date
    total: Decimal
    running: Decimal


@dataclass(frozen=True)
class MonthPoint:
    month: date
    total: Decimal
    label: str  # "Jun", or "Jan '27" when the range crosses a year
    selected: bool


@dataclass(frozen=True)
class Biggest:
    id: str
    amount: Decimal
    spent_on: date
    category_name: str
    icon: Icon


@dataclass(frozen=True)
class Comparison:
    direction: str | None  # "up" | "down" | "same" | None (nothing to compare with)
    value: str  # "▲ 12%", "▼ 8%", "0%" or "—"
    text: str  # "vs 1–22 Oct (Rs 5,760)", "vs October (Rs 8,100)", "No data for October", ...


@dataclass(frozen=True)
class AnalyticsView:
    today: date
    current_month: date
    month: date
    first_month: date
    is_current_month: bool
    month_options: list[tuple[str, str]]
    days_in_month: int
    days_elapsed: int
    total: Decimal
    count: int
    daily_average: Decimal
    biggest: Biggest | None
    comparison: Comparison
    prev_start: date
    prev_has_data: bool
    categories: list[CategoryShare]
    daily: list[DayPoint]
    prev_daily: list[DayPoint]
    six_months: list[MonthPoint]
    biggest_day: DayPoint | None
    aria: dict[str, str] = field(default_factory=dict)
    load_failed: bool = False

    @property
    def month_value(self) -> str:
        return month_value(self.month)

    @property
    def prev_month(self) -> date | None:
        return adjacent_months(self.month, self.first_month, self.current_month)[0]

    @property
    def next_month(self) -> date | None:
        return adjacent_months(self.month, self.first_month, self.current_month)[1]

    @property
    def has_expenses(self) -> bool:
        return self.count > 0

    @property
    def show_six_months(self) -> bool:
        return any(point.total > 0 for point in self.six_months)

    @property
    def cumulative_rows(self) -> list[tuple[int, Decimal | None, Decimal | None]]:
        """(day, running this month, running last month) for the chart 3 data table. None past a month's end."""
        length = max(self.days_in_month, len(self.prev_daily))
        rows = []
        for i in range(length):
            current = self.daily[i].running if i < len(self.daily) else None
            previous = self.prev_daily[i].running if i < len(self.prev_daily) else None
            rows.append((i + 1, current, previous))
        return rows


def stat_size(text: str) -> str:
    """Size tier for a stat card value, so long amounts shrink instead of overflowing."""
    if len(text) <= 8:
        return "lg"
    if len(text) <= 10:
        return "md"
    return "sm"


def _percent(part: Decimal, whole: Decimal) -> int:
    if whole <= 0:
        return 0
    return int((part / whole * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _icon(icon_type: str, icon_value: str) -> Icon:
    url = storage.icon_url(icon_value) if icon_type == "image" else None
    return Icon(icon_type=icon_type, icon_value=icon_value, icon_url=url)


def fetch_month_analytics(month: date, today: date) -> dict:
    """The raw `get_month_analytics` JSON for `month` (the database may clamp it to the current month)."""
    try:
        data = (
            user_client()
            .rpc("get_month_analytics", {"p_month_start": month.isoformat(), "p_today": today.isoformat()})
            .execute()
            .data
        )
    except CAUGHT as error:
        raise friendly(error) from None
    if isinstance(data, list):
        data = data[0] if data else {}
    return data or {}


def _days(rows: list[dict], first: date) -> list[DayPoint]:
    return [
        DayPoint(
            day=first.replace(day=int(row["day"])),
            total=to_decimal(row["total"]),
            running=to_decimal(row["running"]),
        )
        for row in rows or []
    ]


def _comparison(data: dict, total: Decimal, prev_start: date, is_current: bool) -> Comparison:
    prev = data["prev"]
    prev_name = month_name(prev_start)
    if not prev["has_data"]:
        return Comparison(None, "—", f"No data for {prev_name}")

    # For a past month the window is the whole previous month, so window_total == full_total.
    window_end = parse_iso_date(prev["window_end"]) or prev_start
    window_total = to_decimal(prev["window_total"])
    window_label = day_range_label(prev_start, window_end) if is_current else prev_name
    if window_total <= 0:
        return Comparison(None, "—", f"Nothing spent {window_label}")

    text = f"vs {window_label} ({money(window_total)})"
    diff = total - window_total
    if diff == 0:
        return Comparison("same", "0%", text)
    pct = _percent(abs(diff), window_total)
    shown = "<1%" if pct == 0 else f"{pct}%"
    return Comparison("up", f"▲ {shown}", text) if diff > 0 else Comparison("down", f"▼ {shown}", text)


def _six_months(rows: list[dict], selected: date) -> list[MonthPoint]:
    months = [month_from_value(row["month"]) for row in rows or []]
    crosses_year = bool(months) and months[0].year != months[-1].year
    points = []
    for month, row in zip(months, rows or []):
        label = month_short(month)
        if crosses_year and month.month == 1:
            label += f" '{month:%y}"
        points.append(MonthPoint(month=month, total=to_decimal(row["total"]), label=label, selected=month == selected))
    return points


def _aria(view_month: date, total: Decimal, days_elapsed: int, categories: list[CategoryShare],
          biggest_day: DayPoint | None, prev_start: date, prev_has_data: bool,
          prev_daily: list[DayPoint], daily: list[DayPoint], six: list[MonthPoint]) -> dict[str, str]:
    label = month_label(view_month)
    name = month_name(view_month)
    prev_name = month_name(prev_start)
    aria: dict[str, str] = {}

    if categories:
        top = categories[0]
        aria["donut"] = (
            f"{top.name} was your top category at {top.pct_label} of {money(total)}. "
            f"{len(categories)} {'category' if len(categories) == 1 else 'categories'} in total."
        )
    if biggest_day:
        aria["daily"] = (
            f"Daily spending for {label}, {days_elapsed} {'day' if days_elapsed == 1 else 'days'}. "
            f"Your biggest day was {short_date(biggest_day.day)} at {money(biggest_day.total)}."
        )
    if daily:
        last = daily[-1]
        sentence = f"By day {last.day.day} you had spent {money(last.running)} in {name}"
        if prev_has_data and prev_daily:
            same_day = prev_daily[min(last.day.day, len(prev_daily)) - 1]
            aria["cumulative"] = (
                f"{sentence}, compared with {money(same_day.running)} by day {same_day.day.day} of {prev_name}."
            )
        else:
            aria["cumulative"] = f"{sentence}. No data for {prev_name} to compare."
    if six:
        highest = max(six, key=lambda p: (p.total, p.month))
        selected = next((p for p in six if p.selected), six[-1])
        first, last_point = six[0], six[-1]
        if first.month == last_point.month:
            span = f"for {month_label(first.month)}"
        elif first.month.year == last_point.month.year:
            span = f"from {month_name(first.month)} to {month_label(last_point.month)}"
        else:
            span = f"from {month_label(first.month)} to {month_label(last_point.month)}"
        aria["six"] = (
            f"Monthly totals {span}. {month_label(selected.month)}: {money(selected.total)}. "
            f"Highest: {month_label(highest.month)} at {money(highest.total)}."
        )
    return aria


def build_analytics(month_param: str | None) -> AnalyticsView:
    """Everything the analytics page needs. Invalid months fall back to the current month."""
    today = karachi_today()
    current = month_start(today)
    requested = parse_month_param(month_param, current) or current
    data = fetch_month_analytics(requested, today)

    month = month_from_value(data["month"])  # the database clamps out-of-range months
    first = min(month_from_value(data["first_month"]), month)
    prev_start = shift_month(month, -1)
    is_current = bool(data["is_current_month"])
    total = to_decimal(data["total"])
    count = int(data["count"])

    categories = []
    for index, row in enumerate(data.get("by_category") or []):
        cat_total = to_decimal(row["total"])
        categories.append(
            CategoryShare(
                id=row["category_id"],
                name=row["name"],
                icon=_icon(row["icon_type"], row["icon_value"]),
                total=cat_total,
                count=int(row["count"]),
                pct=_percent(cat_total, total),
                in_rest=index >= DONUT_SLICES and len(data["by_category"]) > DONUT_SLICES,
            )
        )

    raw_biggest = data.get("biggest")
    biggest = None
    if raw_biggest:
        biggest = Biggest(
            id=raw_biggest["id"],
            amount=to_decimal(raw_biggest["amount"]),
            spent_on=date.fromisoformat(raw_biggest["spent_on"]),
            category_name=raw_biggest["category_name"],
            icon=_icon(raw_biggest["icon_type"], raw_biggest["icon_value"]),
        )

    daily = _days(data.get("daily"), month)
    prev_has_data = bool(data["prev"]["has_data"])
    prev_daily = _days(data.get("prev_daily"), prev_start) if prev_has_data else []
    biggest_day = max(daily, key=lambda p: (p.total, p.day)) if total > 0 and daily else None
    six = _six_months(data.get("six_months"), month)
    days_elapsed = int(data["days_elapsed"])

    return AnalyticsView(
        today=today,
        current_month=current,
        month=month,
        first_month=first,
        is_current_month=is_current,
        month_options=month_options(first, current),
        days_in_month=int(data["days_in_month"]),
        days_elapsed=days_elapsed,
        total=total,
        count=count,
        daily_average=to_decimal(data["daily_average"]),
        biggest=biggest,
        comparison=_comparison(data, total, prev_start, is_current),
        prev_start=prev_start,
        prev_has_data=prev_has_data,
        categories=categories,
        daily=daily,
        prev_daily=prev_daily,
        six_months=six,
        biggest_day=biggest_day,
        aria=_aria(month, total, days_elapsed, categories, biggest_day, prev_start, prev_has_data, prev_daily, daily, six),
    )


def empty_view(month_param: str | None) -> AnalyticsView:
    """The page with no data, for when the database can't be reached (no network calls)."""
    today = karachi_today()
    current = month_start(today)
    month = parse_month_param(month_param, current) or current
    prev_start = shift_month(month, -1)
    return AnalyticsView(
        today=today,
        current_month=current,
        month=month,
        first_month=month,
        is_current_month=month == current,
        month_options=month_options(month, current),
        days_in_month=0,
        days_elapsed=0,
        total=ZERO,
        count=0,
        daily_average=ZERO,
        biggest=None,
        comparison=Comparison(None, "—", f"No data for {month_name(prev_start)}"),
        prev_start=prev_start,
        prev_has_data=False,
        categories=[],
        daily=[],
        prev_daily=[],
        six_months=[],
        biggest_day=None,
        load_failed=True,
    )


def chart_payload(view: AnalyticsView) -> dict:
    """The JSON analytics.js draws from: labels and URLs are built here, so JS does no date or URL logic.

    Money is sent as strings (exact decimals); JS reads them with Number().
    """
    biggest_index = None
    if view.biggest_day:
        biggest_index = next(i for i, p in enumerate(view.daily) if p.day == view.biggest_day.day)
    return {
        "month_short": month_short(view.month),
        "prev_short": month_short(view.prev_start),
        "days_in_month": view.days_in_month,
        "total": str(view.total),
        "has_prev": view.prev_has_data,
        "donut_slices": DONUT_SLICES,
        "categories": [{"name": c.name, "total": str(c.total), "pct": c.pct} for c in view.categories],
        "daily": [
            {
                "day": p.day.day,
                "total": str(p.total),
                "running": str(p.running),
                "label": short_date(p.day),
                "url": url_for("expenses.dashboard", month=view.month_value, day=p.day.isoformat()),
            }
            for p in view.daily
        ],
        "biggest_day_index": biggest_index,
        "prev_daily": [{"day": p.day.day, "running": str(p.running)} for p in view.prev_daily],
        "six_months": [
            {
                "label": p.label,
                "title": month_label(p.month),
                "total": str(p.total),
                "url": url_for("analytics.index", month=month_value(p.month)),
                "selected": p.selected,
            }
            for p in view.six_months
        ],
    }
