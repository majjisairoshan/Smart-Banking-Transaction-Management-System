"""CTPB Bank — application entry point (Flask app factory).

Run:  python app.py            (dev server, threaded)
      python -m scripts.seed --create-db --seed   (first-time DB setup)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from flask import Flask, g, render_template, session

from bank.config import Config
from bank.db import ensure_schema, init_pool
from bank.services import AdminService, AuthService, BankingService
from bank.utils import initials, inr, ist, mask_account


def create_app(cfg: Config | None = None) -> Flask:
    cfg = cfg or Config.from_env()
    app = Flask(__name__)
    app.secret_key = cfg.secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=cfg.session_lifetime,
        MAX_CONTENT_LENGTH=1024 * 1024,  # 1 MB — forms only
    )

    pool = init_pool(cfg.dsn, cfg.db_pool_min, cfg.db_pool_max)
    ensure_schema(pool)  # idempotent DDL — safe on every boot

    app.extensions["ctpb"] = {
        "cfg": cfg,
        "auth": AuthService(pool),
        "banking": BankingService(pool, cfg),
        "admin": AdminService(pool, cfg),
    }

    from bank.routes.admin import admin_bp
    from bank.routes.api import api_bp
    from bank.routes.auth import auth_bp
    from bank.routes.user import user_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def load_current_user() -> None:
        g.current_user = None
        uid = session.get("user_id")
        if uid is not None:
            g.current_user = app.extensions["ctpb"]["auth"].get_user(int(uid))
            if g.current_user is None:  # deleted user / stale cookie
                session.clear()

    app.add_template_filter(ist, "ist")
    app.add_template_filter(inr, "inr")
    app.add_template_filter(mask_account, "mask")
    app.add_template_filter(initials, "initials")

    @app.context_processor
    def inject_globals():
        return {
            "cfg": cfg,
            "now_utc": datetime.now(UTC),
            "user": g.get("current_user"),
        }

    @app.errorhandler(404)
    def not_found(_err):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(_err):
        return render_template("500.html"), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)
