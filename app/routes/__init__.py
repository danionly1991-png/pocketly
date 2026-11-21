from app.routes.auth import auth_bp
from app.routes.categories import categories_bp
from app.routes.expenses import expenses_bp
from app.routes.main import main_bp
from app.routes.placeholders import placeholders_bp

__all__ = ["auth_bp", "categories_bp", "expenses_bp", "main_bp", "placeholders_bp"]
