import json
import platform
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from database import get_connection
from settings import evaluator_runtime_config, get_settings
from result_portability import clone_result, normalize_url


def now_local(app):
    return datetime.now(ZoneInfo(get_settings()["app_timezone"])).replace(tzinfo=None)


def request_evaluation(app, payload, attempts=3):
    """Survive a transient evaluator restart without failing the whole experiment."""
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                f"{app.config['EVALUATOR_URL']}/evaluate",
                json=payload,
                timeout=900,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(5)
    raise last_error


def record_evaluator_interruption(cursor, experiment_id, attempt_id, error, wall_seconds, completed_at):
    """Keep service outages separate from website evaluation failures."""
    if attempt_id is not None:
        cursor.execute(
            """UPDATE tranco_attempts SET status='interrupted',
               completed_at=%s,wall_seconds=%s,
               error_category='service_interruption',
               error_message=%s WHERE id=%s""",
            (completed_at, wall_seconds, str(error), attempt_id),
        )
    cursor.execute(
        "UPDATE experiments SET status='queued' WHERE id=%s AND status='running'",
        (experiment_id,),
    )


def pending_evaluation_urls(urls, existing_results):
    """Resume only URLs without a stored result, including stored failures.

    A controlled retry removes its failed result before re-queuing it. Without
    this check, every worker restart silently reevaluates old failures first.
    """
    return [url for url in urls if url not in existing_results]


def reuse_frozen_evaluation(cursor, experiment, url):
    """Copy a compatible observation without changing its date or source evidence."""
    if not experiment.get('reuse_cached_results') or not experiment.get('evaluation_signature'):
        return None
    cursor.execute(
        """SELECT r.* FROM experiment_results r
           JOIN experiments e ON e.id = r.experiment_id
           WHERE r.normalized_url = %s AND r.status = 'completed'
             AND e.evaluation_signature = %s AND e.id <> %s
             AND e.source_type = 'url'
             AND e.axe_include_best_practices = %s
           ORDER BY COALESCE(r.evaluated_at, r.created_at) DESC, r.id DESC
           LIMIT 1""",
        (normalize_url(url), experiment['evaluation_signature'], experiment['id'],
         bool(experiment.get('axe_include_best_practices'))),
    )
    cached = cursor.fetchone()
    if not cached:
        return None
    root = Path('/results/raw').resolve()
    for column in ('source_snapshot_path', 'response_source_path'):
        path = Path(cached[column]).resolve() if cached.get(column) else None
        if path and path.is_relative_to(root) and path.is_file():
            # Keep the submitted spelling so restart checks recognize this URL.
            return clone_result(cursor, dict(cached, url=url), experiment['id'], 'cache')
    return None


def store_result(cursor, experiment_id, item, created_at, observation=None):
    if item.get("status") != "completed":
        cursor.execute(
            """
            INSERT INTO experiment_results (
                experiment_id, url, normalized_url, status, provenance, error_message,
                execution_seconds, evaluated_at, created_at
            ) VALUES (%s, %s, %s, %s, 'fresh', %s, %s, %s, %s)
            """,
            (
                experiment_id, item.get("url"), normalize_url(item.get("url")), "failed",
                item.get("error"), item.get("execution_seconds"), created_at, created_at,
            ),
        )
        if item.get('failure_kind'):
            cursor.execute('UPDATE experiment_results SET acquisition_signals=%s WHERE id=%s',
                (json.dumps([item['failure_kind'], 'retryable' if item.get('retryable') else 'review_required']), cursor.lastrowid))
        if observation:
            attach_dataset_provenance(cursor, cursor.lastrowid, observation)
        return

    from accessibility_taxonomy.inventory import acquired_inventory
    acquired_inventory(item)
    semantic = item.get("semantic", {})
    wave = item.get("wave", {})
    metrics = item.get("html_metrics", {})
    load = item.get("load_metadata", {})
    cursor.execute(
        """
        INSERT INTO experiment_results (
            experiment_id, url, status,
            axe_violations, axe_critical, axe_serious, axe_moderate, axe_minor,
            axe_failed_rules, axe_critical_rules, axe_serious_rules,
            axe_moderate_rules, axe_minor_rules, axe_needs_review, axe_needs_review_rules,
            axe_best_practice_issues, axe_best_practice_rules,
            axe_wcag_violations, axe_wcag_critical, axe_wcag_serious,
            axe_wcag_moderate, axe_wcag_minor, axe_wcag_failed_rules, axe_wcag_needs_review,
            lighthouse_score,
            wave_status, wave_errors, wave_contrast_errors, wave_alerts,
            wave_features, wave_structure, wave_aria, wave_aim_score,
            wave_total_elements, wave_raw_path, wave_error_message,
            wave_credits_used, wave_cost_usd,
            semantic_status, semantic_risk_level, semantic_summary, semantic_findings,
            semantic_input_tokens, semantic_output_tokens, semantic_total_tokens, semantic_cost_usd,
            cost_incurred_usd,
            html_size, dom_nodes, images, images_without_alt, links, buttons,
            forms, inputs, headings, h1_count, language_declared,
            has_main_landmark, has_nav_landmark, has_header_landmark, has_footer_landmark,
            execution_seconds, network_idle_reached, lazy_scroll_steps,
            dom_stable, dom_stability_wait_ms, screenshot_path, screenshot_mode,
            captured_url, page_title, acquisition_signals, source_snapshot_path, response_source_path,
            axe_raw_path, lighthouse_raw_path, semantic_raw_path,
            normalized_url, provenance, evaluated_at, created_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, CAST(%s AS JSON), %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, CAST(%s AS JSON), %s, %s,
            %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            experiment_id, item.get("url"), "completed",
            item.get("axe", {}).get("violations", 0),
            item.get("axe", {}).get("critical", 0),
            item.get("axe", {}).get("serious", 0),
            item.get("axe", {}).get("moderate", 0),
            item.get("axe", {}).get("minor", 0),
            item.get("axe", {}).get("failed_rules", 0),
            item.get("axe", {}).get("critical_rules", 0),
            item.get("axe", {}).get("serious_rules", 0),
            item.get("axe", {}).get("moderate_rules", 0),
            item.get("axe", {}).get("minor_rules", 0),
            item.get("axe", {}).get("needs_review", 0),
            item.get("axe", {}).get("needs_review_rules", 0),
            item.get("axe", {}).get("best_practice_issues", 0),
            item.get("axe", {}).get("best_practice_rules", 0),
            item.get("axe", {}).get("wcag_violations", 0),
            item.get("axe", {}).get("wcag_critical", 0),
            item.get("axe", {}).get("wcag_serious", 0),
            item.get("axe", {}).get("wcag_moderate", 0),
            item.get("axe", {}).get("wcag_minor", 0),
            item.get("axe", {}).get("wcag_failed_rules", 0),
            item.get("axe", {}).get("wcag_needs_review", 0),
            item.get("lighthouse", {}).get("accessibility_score"),
            wave.get("status"), wave.get("errors", 0),
            wave.get("contrast_errors", 0), wave.get("alerts", 0),
            wave.get("features", 0), wave.get("structure", 0),
            wave.get("aria", 0), wave.get("aim_score"),
            wave.get("total_elements", 0), wave.get("raw_path"), wave.get("error"),
            wave.get("credits_used"), wave.get("cost_usd"),
            semantic.get("status"), semantic.get("risk_level"), semantic.get("summary"),
            json.dumps(semantic.get("findings", []), ensure_ascii=False),
            semantic.get("input_tokens"), semantic.get("output_tokens"),
            semantic.get("total_tokens"), semantic.get("cost_usd"),
            float(wave.get("cost_usd") or 0) + float(semantic.get("cost_usd") or 0),
            metrics.get("html_size", 0), metrics.get("dom_nodes", 0),
            metrics.get("images", 0), metrics.get("images_without_alt", 0),
            metrics.get("links", 0), metrics.get("buttons", 0),
            metrics.get("forms", 0), metrics.get("inputs", 0),
            metrics.get("headings", 0), metrics.get("h1_count", 0),
            metrics.get("language_declared"), metrics.get("has_main_landmark", False),
            metrics.get("has_nav_landmark", False), metrics.get("has_header_landmark", False),
            metrics.get("has_footer_landmark", False), item.get("execution_seconds"),
            load.get("network_idle_reached"), load.get("scroll_steps"),
            load.get("dom_stable"), load.get("dom_stability_wait_ms"),
            item.get("screenshot_path"), item.get("screenshot_mode"),
            item.get("acquisition", {}).get("captured_url"),
            item.get("acquisition", {}).get("page_title"),
            json.dumps(item.get("acquisition", {}).get("signals", [])),
            item.get("source_snapshot_path"),
            item.get("response_source_path"),
            item.get("axe", {}).get("raw_path"),
            item.get("lighthouse", {}).get("raw_path"), semantic.get("raw_path"),
            normalize_url(item.get("url")), "fresh", created_at, created_at,
        ),
    )
    result_id = cursor.lastrowid
    cursor.execute(
        """
        UPDATE experiment_results
        SET same_domain_links=%s, visible_text_length=%s, aria_attributes=%s,
            uses_aria=%s, skip_links=%s, broken_skip_links=%s, doctype=%s,
            valid_html5_doctype=%s, ambiguous_links=%s
        WHERE id=%s
        """,
        (
            metrics.get("same_domain_links"), metrics.get("visible_text_length"),
            metrics.get("aria_attributes"), metrics.get("uses_aria"),
            metrics.get("skip_links"), metrics.get("broken_skip_links"),
            metrics.get("doctype"), metrics.get("valid_html5_doctype"),
            metrics.get("ambiguous_links"),
            result_id,
        ),
    )
    if observation:
        attach_dataset_provenance(cursor, result_id, observation)


def store_environment(cursor, experiment_id, environment, execution_seconds, created_at):
    cursor.execute("DELETE FROM experiment_environment WHERE experiment_id = %s", (experiment_id,))
    cursor.execute(
        """
        INSERT INTO experiment_environment (
            experiment_id, docker_web_image, docker_evaluator_image, python_version,
            node_version, chromium_version, axe_version, lighthouse_version,
            axe_standard, axe_include_best_practices, axe_counting_mode,
            app_timezone,
            openai_model, llm_provider, llm_model, wave_api_version, wave_report_type,
            wave_eval_delay_ms, page_load_timeout_ms, network_idle_timeout_ms,
            page_settle_delay_ms, dom_stability_window_ms, dom_stability_timeout_ms,
            lazy_load_scroll, scroll_step_px, scroll_delay_ms, max_scroll_steps,
            evaluator_concurrency, execution_seconds, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            experiment_id, environment.get("docker_web_image"),
            environment.get("docker_evaluator_image"), environment.get("python_version"),
            environment.get("node_version"), environment.get("chromium_version"),
            environment.get("axe_version"), environment.get("lighthouse_version"),
            environment.get("axe_standard"), environment.get("axe_include_best_practices"),
            environment.get("axe_counting_mode"),
            environment.get("app_timezone"),
            environment.get("openai_model"), environment.get("llm_provider"),
            environment.get("llm_model"), environment.get("wave_api_version"),
            environment.get("wave_report_type"), environment.get("wave_eval_delay_ms"),
            environment.get("page_load_timeout_ms"), environment.get("network_idle_timeout_ms"),
            environment.get("page_settle_delay_ms"), environment.get("dom_stability_window_ms"),
            environment.get("dom_stability_timeout_ms"), environment.get("lazy_load_scroll"),
            environment.get("scroll_step_px"), environment.get("scroll_delay_ms"),
            environment.get("max_scroll_steps"), environment.get("evaluator_concurrency"),
            execution_seconds, created_at,
        ),
    )


def process_experiment(app, experiment_id):
    with app.app_context():
        runtime_config = evaluator_runtime_config(get_settings())
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM experiments WHERE id = %s", (experiment_id,))
        experiment = cursor.fetchone()
        if not experiment or experiment["status"] not in {"queued", "running"}:
            cursor.close()
            conn.close()
            return

        cursor.execute(
            "UPDATE experiments SET status='running' WHERE id=%s AND status IN ('queued','running')",
            (experiment_id,),
        )
        if not cursor.rowcount:
            cursor.close()
            conn.close()
            return
        conn.commit()
        urls = [url.strip() for url in experiment["urls"].splitlines() if url.strip()]
        cursor.execute(
            "SELECT id,url,source_snapshot_path FROM experiment_results WHERE experiment_id = %s",
            (experiment_id,),
        )
        existing_results = {row["url"]: row for row in cursor.fetchall()}
        last_environment = {}

        try:
            for url in pending_evaluation_urls(urls, existing_results):
                cursor.execute("SELECT status FROM experiments WHERE id=%s", (experiment_id,))
                current = cursor.fetchone()
                if not current or current.get("status") == "paused":
                    return
                if reuse_frozen_evaluation(cursor, experiment, url) is not None:
                    conn.commit()
                    continue
                request_payload = {
                        "experiment_id": experiment_id,
                        "urls": [url],

                        "axe_standard": experiment.get("axe_standard") or "wcag22aa",
                        "axe_include_best_practices": bool(experiment.get("axe_include_best_practices")),
                        "runtime_config": runtime_config,
                    }
                quality_policy = experiment.get('acquisition_quality_policy')
                if quality_policy:
                    request_payload['quality_policy'] = (
                        json.loads(quality_policy) if isinstance(quality_policy, str) else quality_policy
                    )
                attempt_id = None
                started_monotonic = time.monotonic()
                try:
                    payload = request_evaluation(app, request_payload)
                except requests.RequestException as error:
                    # A missing evaluator is an infrastructure outage, not a
                    # failed website. Preserve the candidate and try it again
                    # after Docker has restarted the service.
                    record_evaluator_interruption(
                        cursor, experiment_id, attempt_id, error,
                        time.monotonic() - started_monotonic, now_local(app),
                    )
                    conn.commit()
                    time.sleep(30)
                    return
                last_environment = payload.get("environment", last_environment)
                items = payload.get("results") or [{
                    "url": url, "status": "failed",
                    "error": "Evaluator returned no URL result.",
                    "execution_seconds": 0,
                }]
                for item in items:
                    old = existing_results.get(item.get("url"))
                    if old and not old.get("source_snapshot_path"):
                        cursor.execute("DELETE FROM experiment_results WHERE id=%s", (old["id"],))
                    store_result(cursor, experiment_id, item, now_local(app))
                conn.commit()

            cursor.execute("SELECT status FROM experiments WHERE id=%s", (experiment_id,))
            current = cursor.fetchone()
            if not current or current.get("status") == "paused":
                return
            cursor.execute(
                "SELECT COALESCE(SUM(execution_seconds), 0) AS total FROM experiment_results WHERE experiment_id = %s",
                (experiment_id,),
            )
            total_execution = cursor.fetchone()["total"]
            if last_environment:
                # Python orchestrates acquisition in the web/worker image;
                # the Node evaluator no longer embeds a Python runtime.
                last_environment["python_version"] = f"Python {platform.python_version()}"
                store_environment(
                    cursor, experiment_id, last_environment, total_execution, now_local(app)
                )
            cursor.execute(
                "UPDATE experiments SET status = 'completed', completed_at = %s WHERE id = %s",
                (now_local(app), experiment_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            cursor.execute(
                "UPDATE experiments SET status = 'failed', completed_at = %s WHERE id = %s",
                (now_local(app), experiment_id),
            )
            conn.commit()
            raise
        finally:
            cursor.close()
            conn.close()


def run_worker(app, poll_seconds=2, additive_tick=None):
    from remediation_concurrency import concurrency_limit
    from remediation_queue import RemediationQueue
    queue = RemediationQueue(app)
    try:
        while True:
            try:
                with app.app_context():
                    from rag_sync_jobs import process_pending
                    if not queue.active and process_pending():
                        time.sleep(poll_seconds)
                        continue
                    limit = concurrency_limit(get_settings())
                    conn = get_connection()
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("SELECT id FROM remediation_runs WHERE status IN ('queued','running') ORDER BY created_at ASC LIMIT 5")
                    remediations = cursor.fetchall()
                    cursor.execute(
                        "SELECT id FROM experiments WHERE status IN ('queued','running') ORDER BY created_at ASC LIMIT 1"
                    )
                    job = cursor.fetchone()
                    cursor.close()
                    conn.close()
                if queue.dispatch([row['id'] for row in remediations], limit):
                    time.sleep(poll_seconds)
                    continue
                if job:
                    process_experiment(app, job['id'])
                else:
                    with app.app_context():
                        worked = bool(additive_tick and additive_tick())
                    if not worked:
                        time.sleep(poll_seconds)
            except Exception as error:
                print(f"Experiment worker error: {error}", flush=True)
                time.sleep(poll_seconds)
    finally:
        queue.close()
