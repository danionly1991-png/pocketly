from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from app import auth_utils
from app.config import Config
from app.utils.dates import karachi_today, register_filters

# Static files live in <repo>/public/static so Vercel serves them from its CDN
# at /static/..., while Flask serves the same files at the same URLs locally.
PUBLIC_STATIC = Path(__file__).resolve().parent.parent / "public" / "static"


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, static_folder=str(PUBLIC_STATIC), static_url_path="/static")
    app.config.from_object(config_class)

    CSRFProtect(app)
    register_filters(app)

    from app.routes import auth_bp, categories_bp, expenses_bp, main_bp, placeholders_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(placeholders_bp)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def too_large(_error):
        flash("Upload a JPG, PNG or WEBP image under 2 MB.", "error")
        return redirect(url_for("categories.index"))

    @app.errorhandler(CSRFError)
    def csrf_failed(_error):
        if request.endpoint == "auth.establish_session":
            return jsonify(redirect=url_for("auth.link_error")), 400
        flash("Your session timed out. Please try again.", "error")
        # POST-only routes have no page of their own to go back to.
        post_only = {
            "auth.logout": "main.landing",
            "auth.resend_verification": "auth.check_email",
            "expenses.create_expense": "expenses.dashboard",
            "expenses.delete_expense": "expenses.dashboard",
            "categories.update": "categories.index",
            "categories.delete": "categories.index",
        }
        if request.endpoint in post_only:
            return redirect(url_for(post_only[request.endpoint]))
        return redirect(request.full_path.rstrip("?"))

    app.before_request(auth_utils.load_current_user)

    @app.context_processor
    def inject_globals():
        user = auth_utils.current_user()
        return {
            "current_year": karachi_today().year,
            "current_user": user,
            "get_started_url": url_for("expenses.dashboard" if user else "auth.signup"),
            # Signed-in app pages show only the logo in the navbar (the dashboard has its own top bar).
            "app_shell": request.blueprint in {"expenses", "categories", "placeholders"},
        }

    if not (app.config.get("SUPABASE_URL") and app.config.get("SUPABASE_ANON_KEY")):
        app.logger.warning("Supabase keys are not set. Sign up and login won't work until SUPABASE_URL and SUPABASE_ANON_KEY are set.")

    return app
