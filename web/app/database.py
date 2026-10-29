import os
import time
import mysql.connector
from mysql.connector import Error
from flask import current_app


def ensure_column(cursor, table_name, column_name, definition):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )

    if cursor.fetchone()[0] == 0:
        cursor.execute(
            f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}"
        )


def ensure_string_column_default(cursor, table_name, column_name, value):
    """Avoid acquiring a DDL metadata lock when the installed default agrees."""
    cursor.execute("""SELECT COLUMN_DEFAULT FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (table_name, column_name))
    row = cursor.fetchone()
    if row is None:
        raise ValueError('Cannot update the default of a missing column')
    if row[0] != value:
        # Identifiers are internal schema names; the value stays parameterized.
        cursor.execute(f"ALTER TABLE `{table_name}` ALTER COLUMN `{column_name}` SET DEFAULT %s", (value,))


def ensure_experiment_url_capacity(cursor):
    """Widen legacy URL lists without deleting or rewriting observations."""
    cursor.execute("SHOW COLUMNS FROM experiments LIKE 'urls'")
    column = cursor.fetchone()
    if column and column[1].lower() != "longtext":
        cursor.execute("ALTER TABLE experiments MODIFY COLUMN urls LONGTEXT NOT NULL")


def ensure_settings_capacity(cursor):
    """Provider metadata outgrows TEXT; preserve settings while widening storage."""
    cursor.execute("SHOW COLUMNS FROM app_settings LIKE 'setting_value'")
    column = cursor.fetchone()
    if column and column[1].lower() != 'longtext':
        cursor.execute('ALTER TABLE app_settings MODIFY COLUMN setting_value LONGTEXT NOT NULL')


def get_connection():
    if current_app.config.get("TESTING"):
        return None
    connection = mysql.connector.connect(
        host=current_app.config["DB_HOST"],
        port=int(current_app.config["DB_PORT"]),
        database=current_app.config["DB_NAME"],
        user=current_app.config["DB_USER"],
        password=current_app.config["DB_PASSWORD"],
    )
    if current_app.config.get('READ_ONLY'):
        connection.start_transaction(readonly=True)
    return connection


def init_db():
    max_attempts = 100

    for attempt in range(max_attempts):
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key VARCHAR(100) PRIMARY KEY,
                    setting_value LONGTEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                )
            """)
            ensure_settings_capacity(cursor)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS url_category_jobs (
                    id TINYINT PRIMARY KEY DEFAULT 1,
                    status VARCHAR(20) NOT NULL DEFAULT 'idle',
                    total_urls INT NOT NULL DEFAULT 0,
                    completed_urls INT NOT NULL DEFAULT 0,
                    model VARCHAR(255),
                    input_tokens INT NOT NULL DEFAULT 0,
                    output_tokens INT NOT NULL DEFAULT 0,
                    cost_usd DECIMAL(14,8) NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at DATETIME,
                    updated_at DATETIME NOT NULL
                )
            """)
            ensure_column(cursor, "url_category_jobs", "input_tokens", "INT NOT NULL DEFAULT 0")
            ensure_column(cursor, "url_category_jobs", "experiment_id", "INT NULL")
            ensure_column(cursor, "url_category_jobs", "model_config_json", "LONGTEXT NULL")
            ensure_column(cursor, "url_category_jobs", "output_tokens", "INT NOT NULL DEFAULT 0")
            ensure_column(cursor, "url_category_jobs", "cost_usd", "DECIMAL(14,8) NOT NULL DEFAULT 0")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    storage_key CHAR(32) NOT NULL UNIQUE,
                    content_sha256 CHAR(64) NOT NULL,
                    resource_policy VARCHAR(20) NOT NULL DEFAULT 'isolated',
                    observation_count INT NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dataset_observations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id INT NOT NULL,
                    relative_path TEXT NOT NULL,
                    observation_key VARCHAR(255) NOT NULL,
                    pair_key VARCHAR(255) NULL,
                    condition_label VARCHAR(100) NULL,
                    stratum VARCHAR(100) NULL,
                    expected_label TINYINT NULL,
                    content_sha256 CHAR(64) NOT NULL,
                    served_url TEXT NOT NULL,
                    display_name VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
                )
            """)
            ensure_column(cursor, "dataset_observations", "display_name", "VARCHAR(255) NULL")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    urls LONGTEXT NOT NULL,
                    include_semantic BOOLEAN NOT NULL DEFAULT FALSE,
                    include_wave BOOLEAN NOT NULL DEFAULT FALSE,
                    semantic_provider VARCHAR(50) NULL,
                    semantic_model VARCHAR(255) NULL,
                    axe_standard VARCHAR(20) NOT NULL DEFAULT 'wcag22aa',
                    axe_include_best_practices BOOLEAN NOT NULL DEFAULT FALSE,
                    reuse_cached_results BOOLEAN NOT NULL DEFAULT FALSE,
                    evaluation_signature CHAR(64) NULL,
                    experiment_origin VARCHAR(30) NOT NULL DEFAULT 'evaluation',
                    language VARCHAR(10) NOT NULL DEFAULT 'en',
                    status VARCHAR(50) NOT NULL DEFAULT 'registered',
                    created_at DATETIME NOT NULL,
                    completed_at DATETIME NULL,
                    resume_count INT NOT NULL DEFAULT 0,
                    last_resumed_at DATETIME NULL
                )
            """)

            ensure_experiment_url_capacity(cursor)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experiment_environment (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    experiment_id INT NOT NULL,
                    docker_web_image VARCHAR(255) NULL,
                    docker_evaluator_image VARCHAR(255) NULL,
                    python_version VARCHAR(100) NULL,
                    node_version VARCHAR(100) NULL,
                    chromium_version VARCHAR(255) NULL,
                    axe_version VARCHAR(100) NULL,
                    axe_standard VARCHAR(20) NULL,
                    axe_include_best_practices BOOLEAN NULL,
                    axe_counting_mode VARCHAR(50) NULL,
                    app_timezone VARCHAR(100) NULL,
                    lighthouse_version VARCHAR(100) NULL,
                    openai_model VARCHAR(100) NULL,
                    llm_provider VARCHAR(50) NULL,
                    llm_model VARCHAR(255) NULL,
                    wave_api_version VARCHAR(50) NULL,
                    wave_report_type INT NULL,
                    wave_eval_delay_ms INT NULL,
                    page_load_timeout_ms INT NULL,
                    network_idle_timeout_ms INT NULL,
                    page_settle_delay_ms INT NULL,
                    dom_stability_window_ms INT NULL,
                    dom_stability_timeout_ms INT NULL,
                    lazy_load_scroll BOOLEAN NULL,
                    scroll_step_px INT NULL,
                    scroll_delay_ms INT NULL,
                    max_scroll_steps INT NULL,
                    evaluator_concurrency VARCHAR(255) NULL,
                    execution_seconds FLOAT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
                )
            """)

            ensure_column(
                cursor, "experiments", "semantic_provider", "VARCHAR(50) NULL"
            )
            ensure_column(
                cursor, "experiments", "include_wave", "BOOLEAN NOT NULL DEFAULT FALSE"
            )
            ensure_column(
                cursor, "experiments", "semantic_model", "VARCHAR(255) NULL"
            )
            ensure_column(
                cursor, "experiments", "language", "VARCHAR(10) NOT NULL DEFAULT 'en'"
            )
            ensure_column(cursor, "experiments", "axe_standard", "VARCHAR(20) NOT NULL DEFAULT 'wcag22aa'")
            ensure_column(cursor, "experiments", "axe_include_best_practices", "BOOLEAN NOT NULL DEFAULT FALSE")
            ensure_column(cursor, "experiments", "reuse_cached_results", "BOOLEAN NOT NULL DEFAULT FALSE")
            ensure_column(cursor, "experiments", "evaluation_signature", "CHAR(64) NULL")
            ensure_column(cursor, "experiments", "experiment_origin", "VARCHAR(30) NOT NULL DEFAULT 'evaluation'")
            ensure_column(cursor, "experiments", "source_type", "VARCHAR(20) NOT NULL DEFAULT 'url'")
            ensure_column(cursor, "experiments", "dataset_id", "INT NULL")
            ensure_column(cursor, "experiments", "resource_policy", "VARCHAR(20) NOT NULL DEFAULT 'external'")
            ensure_column(cursor, "experiments", "resume_count", "INT NOT NULL DEFAULT 0")
            ensure_column(cursor, "experiments", "last_resumed_at", "DATETIME NULL")
            ensure_column(cursor, "experiments", "acquisition_quality_policy", "JSON NULL")
            ensure_column(cursor, "experiments", "import_provenance_json", "JSON NULL")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tranco_samples (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    experiment_id INT NOT NULL UNIQUE,
                    list_id VARCHAR(100) NOT NULL,
                    list_sha256 CHAR(64) NOT NULL,
                    source_filename VARCHAR(255) NOT NULL,
                    frame_size INT NOT NULL,
                    sampling_seed VARCHAR(100) NOT NULL,
                    sample_per_stratum INT NOT NULL,
                    reserve_per_stratum INT NOT NULL,
                    strata JSON NOT NULL,
                    candidates JSON NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tranco_attempts (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    experiment_id INT NOT NULL,
                    url VARCHAR(2048) NOT NULL,
                    attempt_number INT NOT NULL,
                    status VARCHAR(30) NOT NULL,
                    started_at DATETIME NOT NULL,
                    completed_at DATETIME NULL,
                    wall_seconds DOUBLE NULL,
                    evaluator_seconds DOUBLE NULL,
                    error_category VARCHAR(80) NULL,
                    error_message TEXT NULL,
                    INDEX idx_tranco_attempts_experiment (experiment_id),
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
                )
            """)
            ensure_column(
                cursor, "experiment_environment", "llm_provider", "VARCHAR(50) NULL"
            )
            ensure_column(
                cursor, "experiment_environment", "llm_model", "VARCHAR(255) NULL"
            )
            ensure_column(
                cursor, "experiment_environment", "wave_api_version", "VARCHAR(50) NULL"
            )
            ensure_column(
                cursor, "experiment_environment", "wave_report_type", "INT NULL"
            )
            environment_columns = {
                "wave_eval_delay_ms": "INT NULL",
                "page_load_timeout_ms": "INT NULL",
                "network_idle_timeout_ms": "INT NULL",
                "page_settle_delay_ms": "INT NULL",
                "dom_stability_window_ms": "INT NULL",
                "dom_stability_timeout_ms": "INT NULL",
                "lazy_load_scroll": "BOOLEAN NULL",
                "scroll_step_px": "INT NULL",
                "scroll_delay_ms": "INT NULL",
                "max_scroll_steps": "INT NULL",
                "evaluator_concurrency": "VARCHAR(255) NULL",
                "axe_standard": "VARCHAR(20) NULL",
                "axe_include_best_practices": "BOOLEAN NULL",
                "axe_counting_mode": "VARCHAR(50) NULL",
                "app_timezone": "VARCHAR(100) NULL",
            }
            for column_name, definition in environment_columns.items():
                ensure_column(cursor, "experiment_environment", column_name, definition)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experiment_results (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    experiment_id INT NOT NULL,
                    url TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    axe_violations INT DEFAULT 0,
                    axe_critical INT DEFAULT 0,
                    axe_serious INT DEFAULT 0,
                    axe_moderate INT DEFAULT 0,
                    axe_minor INT DEFAULT 0,
                    axe_failed_rules INT DEFAULT 0,
                    axe_critical_rules INT DEFAULT 0,
                    axe_serious_rules INT DEFAULT 0,
                    axe_moderate_rules INT DEFAULT 0,
                    axe_minor_rules INT DEFAULT 0,
                    axe_needs_review INT DEFAULT 0,
                    axe_needs_review_rules INT DEFAULT 0,
                    axe_best_practice_issues INT NULL,
                    axe_best_practice_rules INT NULL,
                    axe_wcag_violations INT NULL,
                    axe_wcag_critical INT NULL,
                    axe_wcag_serious INT NULL,
                    axe_wcag_moderate INT NULL,
                    axe_wcag_minor INT NULL,
                    axe_wcag_failed_rules INT NULL,
                    axe_wcag_needs_review INT NULL,
                    lighthouse_score INT NULL,
                    wave_status VARCHAR(50) NULL,
                    wave_errors INT DEFAULT 0,
                    wave_contrast_errors INT DEFAULT 0,
                    wave_alerts INT DEFAULT 0,
                    wave_features INT DEFAULT 0,
                    wave_structure INT DEFAULT 0,
                    wave_aria INT DEFAULT 0,
                    wave_aim_score FLOAT NULL,
                    wave_total_elements INT DEFAULT 0,
                    wave_credits_used INT NULL,
                    wave_cost_usd DECIMAL(14,8) NULL,
                    wave_raw_path TEXT NULL,
                    wave_error_message TEXT NULL,
                    semantic_status VARCHAR(50) NULL,
                    semantic_risk_level VARCHAR(50) NULL,
                    semantic_summary TEXT NULL,
                    semantic_findings JSON NULL,
                    semantic_input_tokens INT NULL,
                    semantic_output_tokens INT NULL,
                    semantic_total_tokens INT NULL,
                    semantic_cost_usd DECIMAL(14,8) NULL,
                    cost_incurred_usd DECIMAL(14,8) NOT NULL DEFAULT 0,
                    html_size INT DEFAULT 0,
                    dom_nodes INT DEFAULT 0,
                    images INT DEFAULT 0,
                    images_without_alt INT DEFAULT 0,
                    links INT DEFAULT 0,
                    buttons INT DEFAULT 0,
                    forms INT DEFAULT 0,
                    inputs INT DEFAULT 0,
                    headings INT DEFAULT 0,
                    h1_count INT DEFAULT 0,
                    language_declared VARCHAR(50) NULL,
                    has_main_landmark BOOLEAN DEFAULT FALSE,
                    has_nav_landmark BOOLEAN DEFAULT FALSE,
                    has_header_landmark BOOLEAN DEFAULT FALSE,
                    has_footer_landmark BOOLEAN DEFAULT FALSE,
                    execution_seconds FLOAT NULL,
                    network_idle_reached BOOLEAN NULL,
                    lazy_scroll_steps INT NULL,
                    dom_stable BOOLEAN NULL,
                    dom_stability_wait_ms INT NULL,
                    screenshot_path TEXT NULL,
                    screenshot_mode VARCHAR(50) NULL,
                    captured_url TEXT NULL,
                    page_title TEXT NULL,
                    acquisition_signals JSON NULL,
                    axe_raw_path TEXT NULL,
                    lighthouse_raw_path TEXT NULL,
                    semantic_raw_path TEXT NULL,
                    source_result_id INT NULL,
                    source_experiment_id INT NULL,
                    provenance VARCHAR(30) NOT NULL DEFAULT 'fresh',
                    normalized_url TEXT NULL,
                    evaluated_at DATETIME NULL,
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
                )
            """)

            wave_result_columns = {
                "wave_status": "VARCHAR(50) NULL",
                "wave_errors": "INT DEFAULT 0",
                "wave_contrast_errors": "INT DEFAULT 0",
                "wave_alerts": "INT DEFAULT 0",
                "wave_features": "INT DEFAULT 0",
                "wave_structure": "INT DEFAULT 0",
                "wave_aria": "INT DEFAULT 0",
                "wave_aim_score": "FLOAT NULL",
                "wave_total_elements": "INT DEFAULT 0",
                "wave_raw_path": "TEXT NULL",
                "wave_error_message": "TEXT NULL",
                "wave_credits_used": "INT NULL",
                "wave_cost_usd": "DECIMAL(14,8) NULL",
            }
            for column_name, definition in wave_result_columns.items():
                ensure_column(
                    cursor, "experiment_results", column_name, definition
                )

            load_result_columns = {
                "network_idle_reached": "BOOLEAN NULL",
                "lazy_scroll_steps": "INT NULL",
                "dom_stable": "BOOLEAN NULL",
                "dom_stability_wait_ms": "INT NULL",
                "screenshot_path": "TEXT NULL",
                "screenshot_mode": "VARCHAR(50) NULL",
                "captured_url": "TEXT NULL",
                "page_title": "TEXT NULL",
                "acquisition_signals": "JSON NULL",
            }
            for column_name, definition in load_result_columns.items():
                ensure_column(cursor, "experiment_results", column_name, definition)

            semantic_usage_columns = {
                "semantic_input_tokens": "INT NULL",
                "semantic_output_tokens": "INT NULL",
                "semantic_total_tokens": "INT NULL",
                "semantic_cost_usd": "DECIMAL(14,8) NULL",
                "cost_incurred_usd": "DECIMAL(14,8) NOT NULL DEFAULT 0",
            }
            for column_name, definition in semantic_usage_columns.items():
                ensure_column(cursor, "experiment_results", column_name, definition)

            axe_result_columns = {
                "axe_failed_rules": "INT DEFAULT 0",
                "axe_critical_rules": "INT DEFAULT 0",
                "axe_serious_rules": "INT DEFAULT 0",
                "axe_moderate_rules": "INT DEFAULT 0",
                "axe_minor_rules": "INT DEFAULT 0",
                "axe_needs_review": "INT DEFAULT 0",
                "axe_needs_review_rules": "INT DEFAULT 0",
                "axe_best_practice_issues": "INT NULL",
                "axe_best_practice_rules": "INT NULL",
                "axe_wcag_violations": "INT NULL",
                "axe_wcag_critical": "INT NULL",
                "axe_wcag_serious": "INT NULL",
                "axe_wcag_moderate": "INT NULL",
                "axe_wcag_minor": "INT NULL",
                "axe_wcag_failed_rules": "INT NULL",
                "axe_wcag_needs_review": "INT NULL",
            }
            for column_name, definition in axe_result_columns.items():
                ensure_column(cursor, "experiment_results", column_name, definition)

            page_feature_columns = {
                "same_domain_links": "INT NULL",
                "visible_text_length": "INT NULL",
                "aria_attributes": "INT NULL",
                "uses_aria": "BOOLEAN NULL",
                "skip_links": "INT NULL",
                "broken_skip_links": "INT NULL",
                "ambiguous_links": "INT NULL",
                "doctype": "VARCHAR(255) NULL",
                "valid_html5_doctype": "BOOLEAN NULL",
                "site_category": "VARCHAR(100) NULL",
                "site_category_source": "VARCHAR(255) NULL",
            }
            for column_name, definition in page_feature_columns.items():
                ensure_column(cursor, "experiment_results", column_name, definition)

            provenance_columns = {
                "source_result_id": "INT NULL",
                "source_experiment_id": "INT NULL",
                "provenance": "VARCHAR(30) NOT NULL DEFAULT 'fresh'",
                "normalized_url": "TEXT NULL",
                "evaluated_at": "DATETIME NULL",
                "dataset_observation_id": "INT NULL",
                "content_sha256": "CHAR(64) NULL",
                "display_name": "VARCHAR(255) NULL",
            }
            for column_name, definition in provenance_columns.items():
                ensure_column(cursor, "experiment_results", column_name, definition)
            ensure_column(cursor, "experiment_results", "source_snapshot_path", "TEXT NULL")
            ensure_column(cursor, "experiment_results", "response_source_path", "TEXT NULL")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediation_templates (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(160) NOT NULL,
                    page_type VARCHAR(60) NOT NULL,
                    description TEXT NULL,
                    html_template LONGTEXT NOT NULL,
                    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediation_runs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    source_result_id INT NOT NULL,
                    template_id INT NULL,
                    title VARCHAR(180) NOT NULL,
                    transformation_format VARCHAR(20) NOT NULL DEFAULT 'html',
                    generator_provider VARCHAR(50) NOT NULL,
                    generator_model VARCHAR(255) NOT NULL,
                    reviewer_provider VARCHAR(50) NOT NULL,
                    reviewer_model VARCHAR(255) NOT NULL,
                    max_iterations INT NOT NULL DEFAULT 3,
                    min_lighthouse INT NOT NULL DEFAULT 96,
                    max_axe INT NOT NULL DEFAULT 3,
                    min_aim DECIMAL(4,1) NULL DEFAULT 9.0,
                    status VARCHAR(30) NOT NULL DEFAULT 'queued',
                    accepted_iteration_id INT NULL,
                    total_input_tokens INT NOT NULL DEFAULT 0,
                    total_output_tokens INT NOT NULL DEFAULT 0,
                    total_cost_usd DECIMAL(14,8) NOT NULL DEFAULT 0,
                    execution_seconds FLOAT NOT NULL DEFAULT 0,
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL,
                    completed_at DATETIME NULL,
                    FOREIGN KEY (source_result_id) REFERENCES experiment_results(id),
                    FOREIGN KEY (template_id) REFERENCES remediation_templates(id) ON DELETE SET NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediation_iterations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    run_id INT NOT NULL,
                    iteration_number INT NOT NULL,
                    prompt_text LONGTEXT NOT NULL,
                    feedback_text TEXT NULL,
                    output_path TEXT NULL,
                    output_url TEXT NULL,
                    decision VARCHAR(20) NOT NULL,
                    decision_reason TEXT NULL,
                    generator_provider VARCHAR(50) NOT NULL,
                    generator_model VARCHAR(255) NOT NULL,
                    reviewer_provider VARCHAR(50) NOT NULL,
                    reviewer_model VARCHAR(255) NOT NULL,
                    input_tokens INT NOT NULL DEFAULT 0,
                    output_tokens INT NOT NULL DEFAULT 0,
                    cost_usd DECIMAL(14,8) NOT NULL DEFAULT 0,
                    execution_seconds FLOAT NOT NULL DEFAULT 0,
                    axe_violations INT NULL,
                    lighthouse_score INT NULL,
                    wave_aim_score DECIMAL(4,1) NULL,
                    created_at DATETIME NOT NULL,
                    UNIQUE KEY unique_run_iteration (run_id, iteration_number),
                    FOREIGN KEY (run_id) REFERENCES remediation_runs(id) ON DELETE CASCADE
                )
            """)
            ensure_column(cursor, "remediation_runs", "accessibility_priority", "INT NOT NULL DEFAULT 70")
            ensure_column(cursor, "remediation_runs", "temperature", "DECIMAL(3,2) NOT NULL DEFAULT 0.15")
            ensure_column(cursor, "remediation_runs", "template_selection", "VARCHAR(20) NOT NULL DEFAULT 'automatic'")
            ensure_column(cursor, "remediation_runs", "template_rationale", "TEXT NULL")
            ensure_column(cursor, "remediation_runs", "use_wave", "BOOLEAN NOT NULL DEFAULT FALSE")
            ensure_column(cursor, "remediation_runs", "model_selection_mode", "VARCHAR(20) NOT NULL DEFAULT 'manual'")
            ensure_column(cursor, "remediation_runs", "use_expert_settings", "BOOLEAN NULL DEFAULT NULL")
            ensure_column(cursor, "remediation_runs", "model_cost_tier", "VARCHAR(20) NOT NULL DEFAULT 'low'")
            ensure_column(cursor, "remediation_runs", "allowed_models_json", "TEXT NULL")
            ensure_column(cursor, "remediation_runs", "current_phase", "VARCHAR(30) NOT NULL DEFAULT 'queued'")
            ensure_column(cursor, "remediation_runs", "current_iteration", "INT NOT NULL DEFAULT 0")
            ensure_column(cursor, "remediation_runs", "progress_percent", "INT NOT NULL DEFAULT 0")
            ensure_column(cursor, "remediation_runs", "progress_message", "VARCHAR(500) NULL")
            ensure_column(cursor, "remediation_runs", "progress_updated_at", "DATETIME NULL")
            ensure_column(cursor, "remediation_runs", "published_experiment_id", "INT NULL")
            ensure_column(cursor, "remediation_runs", "max_dom_distance", "DECIMAL(5,2) NOT NULL DEFAULT 70")
            ensure_column(cursor, "remediation_runs", "enforce_dom_distance", "BOOLEAN NOT NULL DEFAULT FALSE")
            ensure_column(cursor, "remediation_runs", "review_policy", "VARCHAR(30) NOT NULL DEFAULT 'automated'")
            ensure_column(cursor, "remediation_runs", "max_cost_usd", "DECIMAL(10,4) NOT NULL DEFAULT 0.25")
            ensure_column(cursor, "remediation_runs", "max_execution_seconds", "INT NOT NULL DEFAULT 300")
            ensure_column(cursor, "remediation_runs", "use_rag", "BOOLEAN NOT NULL DEFAULT FALSE")
            ensure_column(cursor, "remediation_runs", "generator_evidence_mode", "VARCHAR(24) NOT NULL DEFAULT 'guided'")
            ensure_column(cursor, "remediation_runs", "reconstruction_mode", "VARCHAR(24) NOT NULL DEFAULT 'whole_page'")
            ensure_column(cursor, "remediation_runs", "planner_model", "VARCHAR(150) NOT NULL DEFAULT 'openai/gpt-6-luna'")
            ensure_string_column_default(cursor, "remediation_runs", "planner_model", "openai/gpt-6-luna")
            ensure_column(cursor, "remediation_runs", "markdown_provider", "VARCHAR(24) NOT NULL DEFAULT 'local'")
            ensure_column(cursor, "remediation_runs", "execution_mode", "VARCHAR(24) NOT NULL DEFAULT 'iterative'")
            ensure_column(cursor, "remediation_runs", "local_llm_config_json", "TEXT NULL")
            ensure_column(cursor, "remediation_runs", "model_config_json", "TEXT NULL")
            ensure_column(cursor, "remediation_runs", "harness_config_json", "LONGTEXT NULL")
            ensure_column(cursor, 'remediation_runs', 'intervention_version', "VARCHAR(64) NOT NULL DEFAULT 'five-fixed-levels-v8'")
            ensure_column(cursor, "remediation_runs", "harness_outcome_json", "LONGTEXT NULL")
            ensure_column(cursor, "remediation_runs", "baseline_axe", "INT NULL")
            ensure_column(cursor, "remediation_runs", "baseline_lighthouse", "INT NULL")
            ensure_column(cursor, "remediation_runs", "rag_top_k", "INT NOT NULL DEFAULT 4")
            ensure_column(cursor, "remediation_runs", "diagnosis_policy", "VARCHAR(16) NOT NULL DEFAULT 'disabled'")
            ensure_string_column_default(cursor, "remediation_runs", "diagnosis_policy", "disabled")
            ensure_column(cursor, "remediation_iterations", "wave_credits_used", "INT NOT NULL DEFAULT 0")
            ensure_column(cursor, "remediation_iterations", "wave_cost_usd", "DECIMAL(14,8) NOT NULL DEFAULT 0")
            ensure_column(cursor, "remediation_iterations", "candidate_key", "CHAR(36) NULL")
            ensure_column(cursor, "remediation_iterations", "screenshot_path", "TEXT NULL")
            ensure_column(cursor, "remediation_iterations", "dom_distance", "DECIMAL(5,2) NULL")
            ensure_column(cursor, "remediation_iterations", "original_dom_nodes", "INT NULL")
            ensure_column(cursor, "remediation_iterations", "candidate_dom_nodes", "INT NULL")
            ensure_column(cursor, "remediation_iterations", "dom_changes_json", "JSON NULL")
            ensure_column(cursor, "remediation_iterations", "specialist_reviews_json", "JSON NULL")
            ensure_column(cursor, "remediation_iterations", "agent_usage_json", "JSON NULL")
            ensure_column(cursor, "remediation_iterations", "strategy_json", "JSON NULL")
            ensure_column(cursor, "remediation_iterations", "axe_wcag_violations", "INT NULL")
            ensure_column(cursor, "remediation_iterations", "axe_best_practice_issues", "INT NULL")
            ensure_column(cursor, "remediation_iterations", "axe_metrics_json", "JSON NULL")
            ensure_column(cursor, "remediation_iterations", "axe_raw_path", "TEXT NULL")
            ensure_column(cursor, "remediation_runs", "axe_counting_policy", "VARCHAR(50) NULL")
            ensure_column(cursor, "remediation_runs", "import_provenance_json", "JSON NULL")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediation_events (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    run_id INT NOT NULL,
                    actor VARCHAR(80) NOT NULL,
                    event_type VARCHAR(40) NOT NULL,
                    message VARCHAR(1000) NOT NULL,
                    details_json JSON NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES remediation_runs(id) ON DELETE CASCADE,
                    INDEX idx_remediation_event_run (run_id,id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS browser_remediation_requests (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    url TEXT NOT NULL,
                    normalized_url VARCHAR(2048) NOT NULL,
                    acquisition_experiment_id INT NULL,
                    remediation_run_id INT NULL,
                    model_cost_tier VARCHAR(20) NOT NULL DEFAULT 'low',
                    preservation_level INT NOT NULL DEFAULT 2,
                    use_rag BOOLEAN NOT NULL DEFAULT FALSE,
                    use_wave BOOLEAN NOT NULL DEFAULT FALSE,
                    status VARCHAR(30) NOT NULL DEFAULT 'queued',
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    INDEX idx_browser_request_normalized (normalized_url(191)),
                    FOREIGN KEY (acquisition_experiment_id) REFERENCES experiments(id) ON DELETE SET NULL,
                    FOREIGN KEY (remediation_run_id) REFERENCES remediation_runs(id) ON DELETE SET NULL
                )
            """)
            ensure_column(cursor, "browser_remediation_requests", "configuration_json", "TEXT NULL")
            # Legacy template rows are preserved solely for historical report/import compatibility.
            # No template catalogue is seeded, selected or updated by current runs.

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comparison_studies (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    dimension_label VARCHAR(100) NOT NULL DEFAULT 'Group',
                    notes TEXT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comparison_members (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    comparison_id INT NOT NULL,
                    source_result_id INT NULL,
                    source_experiment_id INT NULL,
                    source_experiment_title VARCHAR(255) NULL,
                    locator TEXT NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    group_label VARCHAR(100) NOT NULL DEFAULT 'Unassigned',
                    group_label_2 VARCHAR(100) NULL,
                    pair_key VARCHAR(255) NULL,
                    is_baseline BOOLEAN NOT NULL DEFAULT FALSE,
                    sort_order INT NOT NULL DEFAULT 0,
                    evaluated_at DATETIME NULL,
                    axe_violations INT NULL,
                    axe_critical INT NULL,
                    axe_serious INT NULL,
                    axe_moderate INT NULL,
                    axe_minor INT NULL,
                    lighthouse_score INT NULL,
                    wave_errors INT NULL,
                    wave_contrast_errors INT NULL,
                    wave_alerts INT NULL,
                    wave_features INT NULL,
                    wave_aim_score FLOAT NULL,
                    semantic_findings_count INT NULL,
                    semantic_risk_level VARCHAR(50) NULL,
                    semantic_provider VARCHAR(50) NULL,
                    semantic_model VARCHAR(255) NULL,
                    semantic_total_tokens INT NULL,
                    created_at DATETIME NOT NULL,
                    UNIQUE KEY unique_comparison_source (comparison_id, source_result_id),
                    FOREIGN KEY (comparison_id) REFERENCES comparison_studies(id) ON DELETE CASCADE
                )
            """)
            comparison_columns = {
                "wave_alerts": "INT NULL",
                "wave_features": "INT NULL",
                "semantic_total_tokens": "INT NULL",
                "group_label_2": "VARCHAR(100) NULL",
                "sort_order": "INT NOT NULL DEFAULT 0",
                "source_remediation_run_id": "INT NULL",
                "source_remediation_iteration_id": "INT NULL",
                "axe_wcag_violations": "INT NULL",
                "axe_best_practice_issues": "INT NULL",
                "axe_metrics_json": "JSON NULL",
            }
            for column_name, definition in comparison_columns.items():
                ensure_column(cursor, "comparison_members", column_name, definition)
            cursor.execute("""
                UPDATE comparison_members m
                JOIN experiments e ON e.id = m.source_experiment_id
                SET m.semantic_findings_count = NULL,
                    m.semantic_risk_level = NULL,
                    m.semantic_total_tokens = NULL
                WHERE e.include_semantic = FALSE
            """)

            cursor.execute("""
                UPDATE dataset_observations
                SET display_name = LEFT(observation_key, 255)
                WHERE display_name IS NULL OR display_name = ''
            """)
            cursor.execute("""
                UPDATE experiment_results r
                LEFT JOIN dataset_observations o ON o.id = r.dataset_observation_id
                SET r.display_name = LEFT(COALESCE(o.display_name, o.observation_key, r.url), 255)
                WHERE r.display_name IS NULL OR r.display_name = ''
            """)

            conn.commit()
            cursor.close()
            conn.close()
            return

        except Error:
            time.sleep(2)

    raise RuntimeError("No fue posible conectar con MySQL después de varios intentos.")
