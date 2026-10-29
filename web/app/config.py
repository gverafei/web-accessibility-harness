import os
from zoneinfo import ZoneInfo
from flask import Request, current_app


class ResearchRequest(Request):
    """Apply deployment byte limits on Flask 3.0 and newer releases alike."""

    @property
    def max_form_memory_size(self):
        return current_app.config["MAX_FORM_MEMORY_SIZE"]

    @property
    def max_form_parts(self):
        return current_app.config["MAX_FORM_PARTS"]


class Config:
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
    DOCUMENTATION_URL = os.getenv("DOCUMENTATION_URL", "")
    PAPER_DOCUMENT_ROOT = os.getenv("PAPER_DOCUMENT_ROOT", "/data/papers")
    SHOW_GLOBAL_SEARCH = os.getenv("SHOW_GLOBAL_SEARCH", "false").lower() == "true"
    MAX_CONTENT_LENGTH = int(os.getenv("HARNESS_MAX_REQUEST_BYTES", "3221225472"))
    # Campaign URL fields share the request byte budget;
    # they must not inherit Flask's 500 KB field / 1,000-part defaults.
    MAX_FORM_MEMORY_SIZE = MAX_CONTENT_LENGTH
    MAX_FORM_PARTS = None
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "a11yharness-session-secret-required"
    )

    EVALUATOR_URL = os.getenv(
        "EVALUATOR_URL",
        "http://evaluator:3000"
    )

    APP_TIMEZONE = ZoneInfo(
        os.getenv("APP_TIMEZONE", "America/Mexico_City")
    )

    BABEL_DEFAULT_LOCALE = "es"
    BABEL_SUPPORTED_LOCALES = ("en", "es")
    BABEL_TRANSLATION_DIRECTORIES = "translations"

    DB_HOST = os.getenv("DB_HOST", "db")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "accessibility_experiments")
    DB_USER = os.getenv("DB_USER", "access_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "access_pass")
