"""Temporary "coming soon" pages for routes that later specs will build.

Only /analytics is left. Remove this file (and its registration in
app/__init__.py) once that route has a real implementation.
"""

from flask import Blueprint, render_template, url_for

from app.auth_utils import login_required

placeholders_bp = Blueprint("placeholders", __name__)

PAGES = {
    "analytics": ("Analytics", "Charts of where your money goes are coming soon."),
}


def _render(name: str):
    heading, message = PAGES[name]
    return render_template(
        "coming_soon.html",
        heading=heading,
        message=message,
        back_url=url_for("expenses.dashboard"),
        back_label="Back to dashboard",
    )


@placeholders_bp.route("/analytics")
@login_required
def analytics():
    return _render("analytics")
