"""Analytics page (Spec 04). Thin: call `app.services.analytics` and render."""

from __future__ import annotations

from flask import Blueprint, flash, render_template, request

from app.auth_utils import login_required
from app.services import analytics as analytics_service
from app.services.db import DataError

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/analytics")
@login_required
def index():
    month_param = request.args.get("month")
    try:
        view = analytics_service.build_analytics(month_param)
    except DataError as error:
        flash(error.user_message, "error")
        view = analytics_service.empty_view(month_param)
    return render_template(
        "analytics.html",
        view=view,
        chart_data=analytics_service.chart_payload(view),
        stat_size=analytics_service.stat_size,
    )
