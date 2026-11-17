"""Entry point for Vercel (auto-detected Flask app) and for `flask run`."""

from app import create_app

app = create_app()
