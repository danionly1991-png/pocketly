"""Temporary "coming soon" pages for routes that later specs will build.

Remove this file (and its registration in app/__init__.py) once every
route below has a real implementation.
"""

from flask import Blueprint, render_template

placeholders_bp = Blueprint("placeholders", __name__)

PAGES = {
    "login": ("Log in", "Logging in to Pocketly is coming in the next update."),
    "signup": ("Create your account", "Sign-ups open very soon. Check back shortly!"),
    "dashboard": ("Your month", "Your monthly spending overview will live here."),
    "analytics": ("Analytics", "Charts showing where your money goes are on the way."),
}


def _render(name: str):
    heading, message = PAGES[name]
    return render_template("coming_soon.html", heading=heading, message=message)


@placeholders_bp.route("/login")
def login():
    return _render("login")


@placeholders_bp.route("/signup")
def signup():
    return _render("signup")


@placeholders_bp.route("/dashboard")
def dashboard():
    return _render("dashboard")


@placeholders_bp.route("/analytics")
def analytics():
    return _render("analytics")
