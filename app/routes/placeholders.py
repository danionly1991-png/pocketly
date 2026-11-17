"""Temporary "coming soon" pages for routes that later specs will build.

Only /analytics is left. Remove this file (and its registration in
app/__init__.py) once that route has a real implementation.
"""

from flask import Blueprint, render_template

placeholders_bp = Blueprint("placeholders", __name__)

PAGES = {
    "analytics": ("Analytics", "Charts showing where your money goes are on the way."),
}


def _render(name: str):
    heading, message = PAGES[name]
    return render_template("coming_soon.html", heading=heading, message=message)


@placeholders_bp.route("/analytics")
def analytics():
    return _render("analytics")
