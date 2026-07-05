"""
config.py
---------
Central application configuration, loaded from environment variables (.env).
Nothing sensitive is hardcoded here - only defaults for local development.
"""

import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Flask core ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    # --- Database ---
    # Defaults to SQLite for local dev. Swap DATABASE_URL to a postgresql://
    # connection string in .env to migrate to PostgreSQL - no code changes needed
    # because we only use standard SQLAlchemy ORM features.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(basedir, "instance", "sla_tracker.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- DFIR-IRIS ---
    IRIS_BASE_URL = os.environ.get("IRIS_BASE_URL", "")
    IRIS_API_KEY = os.environ.get("IRIS_API_KEY", "")
    IRIS_VERIFY_SSL = _bool(os.environ.get("IRIS_VERIFY_SSL"), True)
    IRIS_TIMEOUT_SECONDS = int(os.environ.get("IRIS_TIMEOUT_SECONDS", 30))

    # --- Scheduler ---
    SYNC_INTERVAL_MINUTES = int(os.environ.get("SYNC_INTERVAL_MINUTES", 15))
    SCHEDULER_ENABLED = _bool(os.environ.get("SCHEDULER_ENABLED"), True)
    DAILY_REPORT_ENABLED = _bool(os.environ.get("DAILY_REPORT_ENABLED"), False)
    DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", 7))

    # --- Timezone ---
    DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "UTC")

    # --- Email ---
    EMAIL_NOTIFICATIONS_ENABLED = _bool(os.environ.get("EMAIL_NOTIFICATIONS_ENABLED"), False)
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "")
    SMTP_USE_TLS = _bool(os.environ.get("SMTP_USE_TLS"), True)

    # --- Reports ---
    REPORTS_FOLDER = os.path.join(basedir, os.environ.get("REPORTS_FOLDER", "generated_reports"))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
