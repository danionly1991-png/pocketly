from datetime import date
from pathlib import Path

from flask import Flask, render_template

from app.config import Config

# Static files live in <repo>/public/static so Vercel serves them from its CDN
# at /static/..., while Flask serves the same files at the same URLs locally.
PUBLIC_STATIC = Path(__file__).resolve().parent.parent / "public" / "static"


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, static_folder=str(PUBLIC_STATIC), static_url_path="/static")
    app.config.from_object(config_class)

    from app.routes import main_bp, placeholders_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(placeholders_bp)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.context_processor
    def inject_globals():
        return {"current_year": date.today().year}

    if not (app.config.get("SUPABASE_URL") and app.config.get("SUPABASE_ANON_KEY")):
        app.logger.warning("Supabase keys are not set. That's fine for Part 1; auth arrives in Spec 02.")

    return app
