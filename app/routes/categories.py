"""Category routes: list, create, rename / change icon, delete (moving expenses to "Other")."""

from __future__ import annotations

from dataclasses import dataclass

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import auth_utils
from app.auth_utils import login_required
from app.forms import PRESET_EMOJIS, CategoryForm
from app.services import categories as categories_service
from app.services import storage
from app.services.categories import Category
from app.services.db import DataError

categories_bp = Blueprint("categories", __name__)

DELETE_FALLBACK_MESSAGE = "This category can't be deleted."


@dataclass(frozen=True)
class CategoryRow:
    category: Category
    expense_count: int
    delete_message: str  # text for the confirm dialog


def _plural(n: int) -> str:
    return f"{n} expense" if n == 1 else f"{n} expenses"


def _rows(categories: list[Category], counts: dict[str, int]) -> list[CategoryRow]:
    fallback = next((c for c in categories if c.is_fallback), None)
    rows = []
    for category in categories:
        n = counts.get(category.id, 0)
        if n and fallback:
            message = f"{_plural(n)} will move to {fallback.name}."
        else:
            message = "This can't be undone."
        rows.append(CategoryRow(category, n, message))
    return rows


def _render_index(form: CategoryForm, editing: Category | None = None):
    try:
        categories = categories_service.list_categories()
        counts = categories_service.expense_counts()
    except DataError as error:
        flash(error.user_message, "error")
        categories, counts = [], {}

    return render_template(
        "categories/index.html",
        rows=_rows(categories, counts),
        form=form,
        editing=editing,
        preset_emojis=PRESET_EMOJIS,
    )


def _apply_error(form: CategoryForm, error: DataError) -> None:
    field = getattr(form, error.field, None) if error.field else None
    if field is not None:
        field.errors.append(error.user_message)
    else:
        flash(error.user_message, "error")


@categories_bp.route("/categories")
@login_required
def index():
    editing = None
    edit_id = request.args.get("edit", "")
    form = CategoryForm()
    if edit_id:
        try:
            editing = categories_service.get_category(edit_id)
        except DataError:
            editing = None
        if editing:
            form.name.data = editing.name
            form.icon_type.data = editing.icon_type
            if editing.icon_type == "emoji":
                form.emoji.data = editing.icon_value
    return _render_index(form, editing)


@categories_bp.route("/categories", methods=["POST"])
@login_required
def create():
    form = CategoryForm()
    if form.validate_on_submit():
        user = auth_utils.current_user()
        new_path = None
        try:
            if form.icon_type.data == "image":
                new_path = storage.upload_icon(user.id, form.icon_bytes)
                icon_type, icon_value = "image", new_path
            else:
                icon_type, icon_value = "emoji", form.emoji.data
            categories_service.create_category(form.name.data, icon_type, icon_value)
        except DataError as error:
            storage.remove_icon(new_path)
            _apply_error(form, error)
        else:
            flash("Category added.", "success")
            return redirect(url_for("categories.index"))
    return _render_index(form)


@categories_bp.route("/categories/<uuid:category_id>", methods=["POST"])
@login_required
def update(category_id):
    try:
        old = categories_service.get_category(str(category_id))
    except DataError as error:
        flash(error.user_message, "error")
        return redirect(url_for("categories.index"))
    if old is None:
        abort(404)

    form = CategoryForm()
    form.has_existing_image = old.icon_type == "image"

    if form.validate_on_submit():
        user = auth_utils.current_user()
        new_path = None
        try:
            if form.icon_type.data == "emoji":
                icon_type, icon_value = "emoji", form.emoji.data
            elif form.icon_bytes is not None:
                new_path = storage.upload_icon(user.id, form.icon_bytes)
                icon_type, icon_value = "image", new_path
            else:  # keep the current photo
                icon_type, icon_value = "image", old.icon_value
            updated = categories_service.update_category(str(category_id), form.name.data, icon_type, icon_value)
        except DataError as error:
            storage.remove_icon(new_path)
            _apply_error(form, error)
        else:
            if updated is None:
                storage.remove_icon(new_path)
                abort(404)
            if old.icon_type == "image" and old.icon_value != icon_value:
                storage.remove_icon(old.icon_value)
            flash("Category updated.", "success")
            return redirect(url_for("categories.index"))

    return _render_index(form, editing=old)


@categories_bp.route("/categories/<uuid:category_id>/delete", methods=["POST"])
@login_required
def delete(category_id):
    try:
        categories = categories_service.list_categories()
    except DataError as error:
        flash(error.user_message, "error")
        return redirect(url_for("categories.index"))

    category = next((c for c in categories if c.id == str(category_id)), None)
    if category is None:
        abort(404)
    if category.is_fallback:
        flash(f"{category.name} can't be deleted.", "error")
        return redirect(url_for("categories.index"))

    fallback = next((c for c in categories if c.is_fallback), None)
    try:
        moved = categories_service.delete_category(str(category_id))
    except DataError as error:
        if error.code == "not_found":
            abort(404)
        flash(error.user_message, "error")
        return redirect(url_for("categories.index"))

    if category.icon_type == "image":
        storage.remove_icon(category.icon_value)
    if moved and fallback:
        flash(f"Category deleted. {_plural(moved)} moved to {fallback.name}.", "success")
    else:
        flash("Category deleted.", "success")
    return redirect(url_for("categories.index"))
