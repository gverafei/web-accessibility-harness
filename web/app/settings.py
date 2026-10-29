import os

from database import get_connection
from remediation_model_choices import PROVIDER_DEFAULT_MODELS


def _default_internal_dataset():
    return os.getenv("INTERNAL_DATASET_URLS", "").strip() or "https://example.org/"


READONLY_MODEL_DEFAULTS = {
    "openai_model": PROVIDER_DEFAULT_MODELS['openai'],
    "gemini_model": PROVIDER_DEFAULT_MODELS['google'],
    "llama_model": PROVIDER_DEFAULT_MODELS['meta-llama'],
    "claude_model": PROVIDER_DEFAULT_MODELS['anthropic'],
    "kimi_model": "moonshotai/kimi-k2.5",
    "qwen_model": PROVIDER_DEFAULT_MODELS['qwen'],
    "mistral_model": "mistralai/ministral-8b-2512",
}

SETTING_DEFAULTS = {
    "parallel_remediations": "2",
    "decision_model_catalog_json": "",
    "generative_model_metadata_json": "",
    "decisions_model_metadata_json": "",
    "remediation_min_lighthouse": "90",
    "remediation_max_axe": "5",
    "remediation_max_iterations": "3",
    "remediation_max_cost_usd": "0.25",
    "remediation_max_execution_seconds": "360",
    "remediation_model_catalog_json": "",
    "ollama_base_url": "",
    "ollama_model": "",
    "ollama_capabilities_json": "[]",  # Derived from /api/show, never user input.
    "internal_dataset_urls": _default_internal_dataset(),
    "axe_standard": "wcag22aa",
    "axe_include_best_practices": "false",
    "show_axe_failed_rules": "false",
    "show_axe_needs_review": "false",
    "show_axe_densities": "false",
    "app_timezone": os.getenv("APP_TIMEZONE", "America/Mexico_City").strip(),
    "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", "").strip(),
    "openrouter_base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip(),
    "page_load_timeout_ms": os.getenv("PAGE_LOAD_TIMEOUT_MS", "60000").strip(),
    "network_idle_timeout_ms": os.getenv("NETWORK_IDLE_TIMEOUT_MS", "15000").strip(),
    "page_settle_delay_ms": os.getenv("PAGE_SETTLE_DELAY_MS", "2000").strip(),
    "dom_stability_window_ms": os.getenv("DOM_STABILITY_WINDOW_MS", "1500").strip(),
    "dom_stability_timeout_ms": os.getenv("DOM_STABILITY_TIMEOUT_MS", "10000").strip(),
    "enable_lazy_load_scroll": os.getenv("ENABLE_LAZY_LOAD_SCROLL", "true").strip(),
    "scroll_step_px": os.getenv("SCROLL_STEP_PX", "700").strip(),
    "scroll_delay_ms": os.getenv("SCROLL_DELAY_MS", "400").strip(),
    "max_scroll_steps": os.getenv("MAX_SCROLL_STEPS", "30").strip(),
}

SECRET_SETTINGS = {"openrouter_api_key"}
DERIVED_SETTINGS = {'ollama_capabilities_json'}


def get_settings():
    values = dict(READONLY_MODEL_DEFAULTS, **SETTING_DEFAULTS)
    conn = get_connection()
    if conn is None:  # Lightweight unit-test/application bootstrap fallback.
        try:
            from flask import current_app
            values.update({
                "openrouter_api_key": "configured" if current_app.config.get("OPENROUTER_API_KEY_CONFIGURED") else "",
                "openrouter_base_url": "https://openrouter.ai/api/v1" if current_app.config.get("OPENROUTER_BASE_URL_CONFIGURED") else "",
                "openai_model": current_app.config.get("OPENAI_MODEL", values["openai_model"]),
                "gemini_model": current_app.config.get("GEMINI_MODEL", values["gemini_model"]),
                "llama_model": current_app.config.get("LLAMA_MODEL", values["llama_model"]),
                "claude_model": current_app.config.get("CLAUDE_MODEL", values["claude_model"]),
                "kimi_model": current_app.config.get("KIMI_MODEL", values["kimi_model"]),
                "qwen_model": current_app.config.get("QWEN_MODEL", values["qwen_model"]),
                "mistral_model": current_app.config.get("MISTRAL_MODEL", values["mistral_model"]),
            })
        except RuntimeError:
            pass
        return values
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT setting_key, setting_value FROM app_settings")
    stored_values = {row["setting_key"]: row["setting_value"] for row in cursor.fetchall()}
    values.update({key: value for key, value in stored_values.items() if key in SETTING_DEFAULTS})
    values['internal_dataset_urls'] = values.get('internal_dataset_urls', '').strip() or _default_internal_dataset()
    cursor.close()
    conn.close()
    return values


def save_settings(values):
    values = dict(values)
    if 'parallel_remediations' in values:
        from remediation_concurrency import validate_concurrency
        values['parallel_remediations'] = validate_concurrency(values['parallel_remediations'])
    conn = get_connection()
    cursor = conn.cursor()
    try:
        for key, value in values.items():
            if key not in SETTING_DEFAULTS:
                continue
            if key == 'internal_dataset_urls':
                value = str(value or '').strip() or _default_internal_dataset()
            cursor.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """,
                (key, str(value)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def as_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def evaluator_runtime_config(settings):
    return {
        "openrouter_api_key": settings["openrouter_api_key"],
        "openrouter_base_url": settings["openrouter_base_url"],
        "openai_model": settings["openai_model"],
        "gemini_model": settings["gemini_model"],
        "llama_model": settings["llama_model"],
        "claude_model": settings["claude_model"],
        "kimi_model": settings["kimi_model"],
        "qwen_model": settings["qwen_model"],
        "mistral_model": settings["mistral_model"],
        "page_load_timeout_ms": settings["page_load_timeout_ms"],
        "network_idle_timeout_ms": settings["network_idle_timeout_ms"],
        "page_settle_delay_ms": settings["page_settle_delay_ms"],
        "dom_stability_window_ms": settings["dom_stability_window_ms"],
        "dom_stability_timeout_ms": settings["dom_stability_timeout_ms"],
        "enable_lazy_load_scroll": settings["enable_lazy_load_scroll"],
        "scroll_step_px": settings["scroll_step_px"],
        "scroll_delay_ms": settings["scroll_delay_ms"],
        "max_scroll_steps": settings["max_scroll_steps"],
        "app_timezone": settings["app_timezone"],
    }
