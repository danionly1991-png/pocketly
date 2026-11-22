from flask import Blueprint, render_template

from app.auth_utils import logged_out_only

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@logged_out_only
def landing():
    return render_template("landing.html")
