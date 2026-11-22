"""Dashboard and expense routes. Thin: validate, call `app.services.expenses`, flash, redirect."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.auth_utils import login_required
from app.forms import ExpenseForm
from app.services import categories as categories_service
from app.services import expenses as expenses_service
from app.services.db import DataError
from app.utils.dates import amount_input, karachi_today, month_start, parse_iso_date

expenses_bp = Blueprint("expenses", __name__)


def _load_categories() -> list:
    try:
        return categories_service.list_categories()
    except DataError as error:
        flash(error.user_message, "error")
        return []


def _dashboard_params(month: date, day: date | None, current_month: date) -> dict:
    """Query params for a dashboard URL. The current month is the default, so it is left out."""
    params: dict = {}
    if month != current_month:
        params["month"] = f"{month:%Y-%m}"
    if day:
        params["day"] = day.isoformat()
    return params


def _render_dashboard(view, form: ExpenseForm, categories: list, open_add: bool = False):
    return render_template(
        "dashboard.html",
        view=view,
        form=form,
        categories=categories,
        open_add=open_add,
        today_iso=view.today.isoformat(),
        params=_dashboard_params(view.month, view.day, view.current_month),
        month_params=_dashboard_params(view.month, None, view.current_month),
    )


def _build_view(month_param: str | None, day_param: str | None):
    try:
        return expenses_service.build_dashboard(month_param, day_param)
    except DataError as error:
        flash(error.user_message, "error")
        return expenses_service.empty_view(month_param, day_param)


def _attach_error(form: ExpenseForm, error: DataError) -> None:
    field = getattr(form, error.field, None) if error.field else None
    if field is not None:
        field.errors.append(error.user_message)
    else:
        flash(error.user_message, "error")


@expenses_bp.route("/dashboard")
@login_required
def dashboard():
    view = _build_view(request.args.get("month"), request.args.get("day"))
    categories = _load_categories()

    form = ExpenseForm()
    form.spent_on.data = view.today.isoformat()
    form.return_month.data = view.month_value
    form.return_day.data = view.day_value
    # ?add=1 opens the panel without JavaScript.
    return _render_dashboard(view, form, categories, open_add=request.args.get("add") == "1")


@expenses_bp.route("/expenses", methods=["POST"])
@login_required
def create_expense():
    categories = _load_categories()
    form = ExpenseForm()
    form.allowed_category_ids = frozenset(c.id for c in categories)

    if form.validate_on_submit():
        try:
            created = expenses_service.create_expense(
                form.category_id.data, form.amount_value, form.spent_on_value, form.note.data
            )
        except DataError as error:
            _attach_error(form, error)
        else:
            flash("Expense added.", "success")
            # Go to the month the expense is in. Keep the day filter only if it still shows the new expense.
            today = karachi_today()
            spent_on = created["spent_on"]
            view_day = parse_iso_date(form.return_day.data)
            day = view_day if view_day == spent_on else None
            params = _dashboard_params(month_start(spent_on), day, month_start(today))
            # The anchor scrolls to the new row and tints it briefly (CSS :target).
            return redirect(url_for("expenses.dashboard", _anchor=f"expense-{created['id']}", **params))

    view = _build_view(form.return_month.data, form.return_day.data)
    return _render_dashboard(view, form, categories, open_add=True)


@expenses_bp.route("/expenses/<uuid:expense_id>")
@login_required
def detail(expense_id):
    try:
        expense = expenses_service.get_expense(str(expense_id))
    except DataError as error:
        flash(error.user_message, "error")
        return redirect(url_for("expenses.dashboard"))
    if expense is None:
        abort(404)

    current = month_start(karachi_today())
    back_params = _dashboard_params(month_start(expense.spent_on), None, current)
    return render_template("expenses/detail.html", expense=expense, back_params=back_params)


@expenses_bp.route("/expenses/<uuid:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit(expense_id):
    try:
        expense = expenses_service.get_expense(str(expense_id))
    except DataError as error:
        flash(error.user_message, "error")
        return redirect(url_for("expenses.dashboard"))
    if expense is None:
        abort(404)

    categories = _load_categories()
    form = ExpenseForm()
    form.allowed_category_ids = frozenset(c.id for c in categories)

    if request.method == "GET":
        form.amount.data = amount_input(expense.amount)
        form.category_id.data = expense.category.id
        form.spent_on.data = expense.spent_on.isoformat()
        form.note.data = expense.note or ""
    elif form.validate_on_submit():
        try:
            updated = expenses_service.update_expense(
                str(expense_id), form.category_id.data, form.amount_value, form.spent_on_value, form.note.data
            )
        except DataError as error:
            _attach_error(form, error)
        else:
            if not updated:
                abort(404)
            flash("Expense updated.", "success")
            return redirect(url_for("expenses.detail", expense_id=expense_id))

    return render_template(
        "expenses/edit.html",
        expense=expense,
        form=form,
        categories=categories,
        today_iso=karachi_today().isoformat(),
    )


@expenses_bp.route("/expenses/<uuid:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    try:
        spent_on = expenses_service.delete_expense(str(expense_id))
    except DataError as error:
        flash(error.user_message, "error")
        return redirect(url_for("expenses.detail", expense_id=expense_id))
    if spent_on is None:
        abort(404)

    flash("Expense deleted.", "success")
    params = _dashboard_params(month_start(spent_on), None, month_start(karachi_today()))
    return redirect(url_for("expenses.dashboard", **params))
