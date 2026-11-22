from app.routes.analytics import analytics_bp
from app.routes.auth import auth_bp
from app.routes.categories import categories_bp
from app.routes.expenses import expenses_bp
from app.routes.main import main_bp

__all__ = ["analytics_bp", "auth_bp", "categories_bp", "expenses_bp", "main_bp"]
