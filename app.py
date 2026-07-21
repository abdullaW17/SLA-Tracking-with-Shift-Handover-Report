"""
app.py
------
Application factory + entry point for the Automated SLA Tracking and
Report Generation System.

Run with:
    python app.py
or:
    flask run
"""

import os
import logging
from datetime import timedelta

from flask import Flask, redirect, url_for

from config import config_by_name
from extensions import db, login_manager, migrate, csrf


def create_app(config_name=None):
    config_name = config_name or os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name["development"]))

    # --- Gap #9: Session cookie hardening ---
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(hours=8))

    # Ensure instance/ and generated_reports/ exist for SQLite + report output
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)
    os.makedirs(app.config["REPORTS_FOLDER"], exist_ok=True)

    # --- Extensions ---
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)  # Gap #9: CSRF protection

    # Dynamic migration check to add custom business hours columns to clients table if missing
    with app.app_context():
        try:
            db.session.execute(db.text("SELECT business_hours_start FROM clients LIMIT 1"))
        except Exception:
            db.session.rollback()
            try:
                db.session.execute(db.text("ALTER TABLE clients ADD COLUMN business_hours_start VARCHAR(10)"))
                db.session.execute(db.text("ALTER TABLE clients ADD COLUMN business_hours_end VARCHAR(10)"))
                db.session.execute(db.text("ALTER TABLE clients ADD COLUMN business_hours_days VARCHAR(50)"))
                db.session.commit()
                logging.getLogger(__name__).info("Migrated database: added business hours columns to clients table")
            except Exception as e:
                db.session.rollback()
                logging.getLogger(__name__).error(f"Failed to migrate database columns: {e}")

        # Ensure all models are created (e.g. activity_logs table)
        try:
            db.create_all()
        except Exception as e:
            logging.getLogger(__name__).error(f"db.create_all failed: {e}")

    # --- Models (import after db.init_app so metadata registers correctly) ---
    from models import User  # noqa: F401  (registers all models via models/__init__.py)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- Blueprints ---
    from routes.auth_routes import auth_bp
    from routes.dashboard_routes import dashboard_bp
    from routes.ticket_routes import ticket_bp
    from routes.sla_rule_routes import sla_rule_bp
    from routes.report_routes import report_bp
    from routes.settings_routes import settings_bp
    from routes.api_routes import api_bp
    from routes.handover_routes import handover_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(ticket_bp)
    app.register_blueprint(sla_rule_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(handover_bp)

    @app.route("/")
    def root():
        return redirect(url_for("dashboard.index"))

    # --- Jinja helpers used across templates ---
    from models.ticket import SLA_BADGE_COLOR

    @app.context_processor
    def inject_helpers():
        from services.iris_api_service import fetch_classifications
        
        def severity_display(val):
            if not val:
                return "-"
            try:
                classifications = fetch_classifications()
                for c in classifications:
                    if c.get("name") == val:
                        return c.get("name_expanded") or val
            except Exception:
                pass
            return val

        return dict(
            sla_badge_color=SLA_BADGE_COLOR,
            severity_display=severity_display
        )

    # --- Logging ---
    logging.basicConfig(level=logging.INFO)

    # --- Scheduler (skip during CLI commands like `flask db migrate`) ---
    if not app.config.get("TESTING") and os.environ.get("RUN_SCHEDULER", "1") == "1":
        with app.app_context():
            from services.scheduler_service import init_scheduler
            try:
                init_scheduler(app)
            except Exception:
                logging.getLogger(__name__).exception("Failed to start scheduler")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", True), use_reloader=False)
