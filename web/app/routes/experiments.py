import csv
import json
import os
import shutil
from datetime import datetime
from io import StringIO
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, session, send_file, url_for
from flask_babel import gettext as _

from database import get_connection
from settings import SETTING_DEFAULTS, DERIVED_SETTINGS, SECRET_SETTINGS, get_settings, save_settings


experiments_bp = Blueprint("experiments", __name__)

AXE_STANDARDS = {"wcag20a", "wcag20aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"}
MAX_EXPERIMENT_NAME = 160
TIMEZONE_GROUPS = (
    ("Universal", (("UTC", "UTC"),)),
    ("Mexico", (
        ("America/Mexico_City", "Mexico City — Central Mexico"),
        ("America/Mazatlan", "Mazatlan — Baja California Sur and northwest Mexico"),
        ("America/Tijuana", "Tijuana — Baja California"),
        ("America/Cancun", "Cancun — Quintana Roo"),
        ("America/Chihuahua", "Chihuahua"),
        ("America/Hermosillo", "Hermosillo — Sonora"),
    )),
    ("Americas", (
        ("America/Anchorage", "Anchorage"), ("Pacific/Honolulu", "Honolulu"),
        ("America/Los_Angeles", "Los Angeles / Vancouver"),
        ("America/Denver", "Denver"), ("America/Phoenix", "Phoenix"),
        ("America/Chicago", "Chicago"), ("America/New_York", "New York / Toronto"),
        ("America/Halifax", "Halifax"), ("America/St_Johns", "St. John's"),
        ("America/Bogota", "Bogota / Lima / Quito"),
        ("America/Caracas", "Caracas"), ("America/Santiago", "Santiago"),
        ("America/Sao_Paulo", "Sao Paulo"), ("America/Argentina/Buenos_Aires", "Buenos Aires"),
    )),
    ("Europe and Africa", (
        ("Atlantic/Azores", "Azores"), ("Europe/London", "London / Dublin"),
        ("Europe/Madrid", "Madrid / Paris / Berlin / Rome"),
        ("Europe/Athens", "Athens / Bucharest / Helsinki"),
        ("Europe/Moscow", "Moscow"), ("Africa/Casablanca", "Casablanca"),
        ("Africa/Cairo", "Cairo"), ("Africa/Johannesburg", "Johannesburg"),
        ("Africa/Nairobi", "Nairobi"),
    )),
    ("Asia", (
        ("Asia/Jerusalem", "Jerusalem"), ("Asia/Dubai", "Dubai"),
        ("Asia/Karachi", "Karachi"), ("Asia/Kolkata", "India / Sri Lanka"),
        ("Asia/Dhaka", "Dhaka"), ("Asia/Bangkok", "Bangkok / Jakarta"),
        ("Asia/Singapore", "Singapore / Kuala Lumpur"),
        ("Asia/Shanghai", "Beijing / Shanghai"), ("Asia/Hong_Kong", "Hong Kong"),
        ("Asia/Tokyo", "Tokyo / Seoul"),
    )),
    ("Oceania", (
        ("Australia/Perth", "Perth"), ("Australia/Adelaide", "Adelaide"),
        ("Australia/Brisbane", "Brisbane"), ("Australia/Sydney", "Sydney / Melbourne"),
        ("Pacific/Auckland", "Auckland"), ("Pacific/Fiji", "Fiji"),
    )),
)
TIMEZONE_CHOICES = {
    value for _group, choices in TIMEZONE_GROUPS for value, _label in choices
}
CLEAR_EXPERIMENTS_PHRASE = "DELETE ALL EXPERIMENTS"


def build_experiments_summary(experiments_data):
    from summary_metrics import evaluation_run_summary
    return {
        **evaluation_run_summary(experiments_data),
        "total_experiments": len(experiments_data),
        "completed_experiments": sum(item.get("status") == "completed" for item in experiments_data),
        "wave_experiments": sum(bool(item.get("include_wave")) for item in experiments_data),
        "processed_urls": sum(item.get("processed_urls") or 0 for item in experiments_data),
        "wave_credits": sum(item.get("wave_credits") or 0 for item in experiments_data),
        "total_cost": round(sum(float(item.get("total_cost") or 0) for item in experiments_data), 6),
    }


def now_local():
    timezone = ZoneInfo(get_settings()["app_timezone"])
    return datetime.now(timezone).replace(tzinfo=None)


@experiments_bp.route("/language/<language>", methods=["GET"])
def set_language(language):
    supported = current_app.config["BABEL_SUPPORTED_LOCALES"]
    if language not in supported:
        language = "en"

    session["language"] = language
    next_url = request.args.get("next", "")
    parsed = urlsplit(next_url)

    if parsed.scheme or parsed.netloc or not next_url.startswith("/"):
        next_url = url_for("workspace.launch")

    return redirect(next_url)


@experiments_bp.route("/theme/<theme>", methods=["GET", "POST"])
def set_theme(theme):
    if theme not in {"light", "dark", "system"}:
        theme = "light"
    session["ui_theme"] = theme
    if request.method == "POST":
        return jsonify(theme=theme)
    next_url = request.args.get("next", "")
    parsed = urlsplit(next_url)
    if parsed.scheme or parsed.netloc or not next_url.startswith("/"):
        next_url = url_for("workspace.launch")
    return redirect(next_url)


@experiments_bp.route("/analytics", methods=["GET"])
def index():
    from dashboard_activity import activity
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        board = activity(cursor, request.args, now_local(), timezone_name=get_settings()['app_timezone'])
    finally:
        cursor.close()
        connection.close()
    return render_template('dashboard.html', activity=board)


@experiments_bp.get('/dashboard/activity')
def dashboard_activity():
    from dashboard_activity import activity
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        board = activity(cursor, request.args, now_local(), timezone_name=get_settings()['app_timezone'])
    finally:
        cursor.close()
        connection.close()
    response = jsonify(board)
    response.headers['Cache-Control'] = 'no-store'
    return response


@experiments_bp.route("/configuration", methods=["GET", "POST"])
def configuration():
    from local_llm import local_configuration, installed_local_models
    settings = get_settings()
    if request.method == "GET" and request.args.get("tab") in ("generative", "decisions"):
        return redirect(url_for("components.models", tab=request.args["tab"]))
    if request.method == "POST":
        from harness.routes import protect
        protect()
        values = {}
        for key in SETTING_DEFAULTS:
            if key in DERIVED_SETTINGS or key.startswith("remediation_") or key.startswith("ollama_"):
                continue
            if key in {'remediation_model_catalog_json','decision_model_catalog_json','generative_model_metadata_json','decisions_model_metadata_json'}:
                continue  # Saved independently by the validated catalogue editor.
            if key in SECRET_SETTINGS:
                submitted = request.form.get(key, "").strip()
                values[key] = submitted or settings[key]
            elif key in {"axe_include_best_practices", "show_axe_failed_rules", "show_axe_needs_review", "show_axe_densities", "enable_lazy_load_scroll"}:
                values[key] = "true" if request.form.get(key) == "on" else "false"
            else:
                values[key] = request.form.get(key, settings[key]).strip()
        from remediation_concurrency import validate_concurrency
        try:
            values['parallel_remediations'] = validate_concurrency(values['parallel_remediations'])
        except ValueError:
            flash(_('Choose between 1 and 5 simultaneous remediation runs.'), 'danger')
            return redirect(url_for('experiments.configuration'))
        if values["axe_standard"] not in AXE_STANDARDS:
            values["axe_standard"] = "wcag22aa"
        try:
            ZoneInfo(values["app_timezone"])
            if values["app_timezone"] not in TIMEZONE_CHOICES:
                raise ZoneInfoNotFoundError(values["app_timezone"])
        except ZoneInfoNotFoundError:
            values["app_timezone"] = settings["app_timezone"] if settings["app_timezone"] in TIMEZONE_CHOICES else "America/Mexico_City"
        save_settings(values)
        flash(_("Configuration saved. New experiments will use these values."), "success")
        return redirect(url_for("experiments.configuration"))

    axe_version = "unknown"
    try:
        if current_app.testing: raise requests.RequestException('Isolated configuration render')
        response = requests.get(f"{current_app.config['EVALUATOR_URL']}/health", timeout=3)
        response.raise_for_status()
        axe_version = response.json().get("axe_version", "unknown")
    except requests.RequestException:
        pass
    return render_template(
        "configuration.html",
        settings=settings,
        local_models=[],
        local_models_error=False,
        axe_version=axe_version,
        timezone_groups=TIMEZONE_GROUPS,
        clear_experiments_phrase=CLEAR_EXPERIMENTS_PHRASE,
        decision_editor=request.args.get('tab')=='decisions',
        catalog=__import__('remediation_model_choices').configured_catalog(settings),
        decision_catalog=__import__('harness.decision_models',fromlist=['catalogue']).catalogue(settings),
    )


@experiments_bp.post('/configuration/test-ollama')
def test_ollama():
    from local_llm import installed_local_models
    try:
        saved = get_settings()
        address = request.form.get('ollama_base_url', saved.get('ollama_base_url'))
        model = request.form.get('ollama_model', saved.get('ollama_model'))
        installed = {item['id'] for item in installed_local_models(address)}
        if model and model not in installed:
            raise ValueError('The configured model is not installed on this Ollama server.')
        flash(_('Ollama connection verified. No generation was performed; save configuration to keep your selection.'), 'success')
    except (ValueError, KeyError, requests.RequestException):
        flash(_('Could not verify Ollama. Check the server address, installed model and worker connectivity.'), 'danger')
    return redirect(url_for('experiments.configuration'))


@experiments_bp.post('/configuration/ollama-models')
def ollama_models():
    from local_llm import installed_local_models
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify({'models': installed_local_models(payload.get('base_url'))})
    except ValueError as error:
        return jsonify({'error': _(str(error))}), 400
    except requests.RequestException:
        return jsonify({'error': _('Could not load installed models. Check the Ollama server address and connectivity.')}), 400


@experiments_bp.route("/experiments", methods=["GET"])
@experiments_bp.route("/evaluations", methods=["GET"])
def experiments():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT e.id, e.title, e.urls, e.include_wave, e.status, e.created_at,
               e.completed_at, e.experiment_origin, e.reuse_cached_results,
               e.source_type, e.resume_count, e.last_resumed_at,
               (SELECT JSON_ARRAYAGG(r.id) FROM experiment_results r WHERE r.experiment_id = e.id AND r.status = 'completed') AS review_result_ids,
               (SELECT COUNT(*) FROM experiment_results r WHERE r.experiment_id = e.id) AS processed_urls,
               (SELECT COUNT(*) FROM experiment_results r WHERE r.experiment_id = e.id AND r.status = 'completed') AS completed_urls,
               (SELECT COUNT(*) FROM experiment_results r WHERE r.experiment_id = e.id AND r.provenance <> 'fresh') AS reused_urls,
               (SELECT COUNT(*) FROM experiment_results r WHERE r.experiment_id = e.id AND r.status = 'failed') AS failed_urls,
               (SELECT COALESCE(SUM(r.wave_credits_used), 0) FROM experiment_results r WHERE r.experiment_id = e.id) AS wave_credits,
               (SELECT COALESCE(SUM(r.wave_cost_usd), 0) FROM experiment_results r WHERE r.experiment_id = e.id) AS total_cost,
               (SELECT COALESCE(SUM(r.execution_seconds), 0) FROM experiment_results r WHERE r.experiment_id = e.id) AS execution_seconds,
               (SELECT SUM(r.axe_wcag_violations) FROM experiment_results r WHERE r.experiment_id = e.id AND r.status = 'completed') AS axe_total,
               (SELECT ROUND(AVG(r.lighthouse_score), 1) FROM experiment_results r WHERE r.experiment_id = e.id AND r.status = 'completed') AS lighthouse_mean,
               (SELECT ROUND(AVG(r.wave_aim_score), 1) FROM experiment_results r WHERE r.experiment_id = e.id AND r.status = 'completed') AS wave_mean
        FROM experiments e
        ORDER BY id DESC
    """)

    all_experiments = cursor.fetchall()
    from summary_metrics import evaluation_metrics
    measured_summary = evaluation_metrics(cursor) if all_experiments else {}
    query = request.args.get("q", "").strip()
    if query:
        needle = query.casefold()
        if needle.startswith("#") and needle[1:].isdigit():
            needle = needle[1:]
        search_fields = (
            "id", "title", "urls", "status", "experiment_origin",
        )
        experiments_data = [
            item for item in all_experiments
            if any(needle in str(item.get(field) or "").casefold() for field in search_fields)
        ]
    else:
        experiments_data = all_experiments

    cursor.close()
    conn.close()

    return render_template(
        "experiments.html",
        experiments=experiments_data,
        summary={**build_experiments_summary(all_experiments), **measured_summary},
        query=query,
    )


@experiments_bp.route("/experiments/<int:experiment_id>/title", methods=["POST"])
def rename_experiment(experiment_id):
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > MAX_EXPERIMENT_NAME:
        return jsonify({"ok": False, "error": _("Use a name between 1 and %(count)s characters.", count=MAX_EXPERIMENT_NAME)}), 400
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM experiments WHERE id=%s", (experiment_id,))
    if not cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": _("The evaluation does not exist.")}), 404
    cursor.execute("UPDATE experiments SET title=%s WHERE id=%s", (title, experiment_id))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True, "title": title})


@experiments_bp.route("/experiments/search-suggestions", methods=["GET"])
def experiment_search_suggestions():
    query = request.args.get("q", "").strip()
    like = f"%{query}%"
    evaluation_id = query.removeprefix("#")
    evaluation_id = evaluation_id if evaluation_id.isascii() and evaluation_id.isdigit() else None
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, title, status, created_at
        FROM experiments
        WHERE %s = '' OR title LIKE %s OR urls LIKE %s OR status LIKE %s
              OR experiment_origin LIKE %s OR id = %s
        ORDER BY created_at DESC
        LIMIT 6
        """,
        (query, like, like, like, like, evaluation_id),
    )
    experiments_found = cursor.fetchall()
    cursor.execute(
        """
        SELECT r.experiment_id, r.url, e.title
        FROM experiment_results r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE %s <> '' AND r.url LIKE %s
        ORDER BY r.id DESC
        LIMIT 6
        """,
        (query, like),
    )
    urls_found = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({
        "experiments": [
            {
                "id": item["id"], "title": item["title"],
                "status": item["status"], "date": str(item["created_at"]),
                "href": url_for("experiments.experiment_report_loading", experiment_id=item["id"]),
            }
            for item in experiments_found
        ],
        "urls": [
            {
                "experiment_id": item["experiment_id"], "url": item["url"],
                "title": item["title"],
                "href": url_for("experiments.experiment_report_loading", experiment_id=item["experiment_id"]) + "#url-results",
            }
            for item in urls_found
        ],
    })


@experiments_bp.route("/experiments/<int:experiment_id>/resume", methods=["POST"])
def resume_experiment(experiment_id):
    """Resume only the unfinished portion of an interrupted experiment."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, status, urls FROM experiments WHERE id=%s FOR UPDATE",
            (experiment_id,),
        )
        experiment = cursor.fetchone()
        if not experiment:
            raise ValueError("missing")
        if experiment.get("status") not in {"failed", "paused"}:
            raise ValueError("not_resumable")
        cursor.execute(
            "SELECT COUNT(*) AS processed FROM experiment_results WHERE experiment_id=%s",
            (experiment_id,),
        )
        processed = int(cursor.fetchone()["processed"] or 0)
        total = len([url for url in (experiment.get("urls") or "").splitlines() if url.strip()])
        cursor.execute(
            """
            UPDATE experiments
            SET status='queued', completed_at=NULL,
                resume_count=resume_count+1, last_resumed_at=%s
            WHERE id=%s
            """,
            (now_local(), experiment_id),
        )
        conn.commit()
    except ValueError as error:
        conn.rollback()
        messages = {
            "missing": _("The requested evaluation experiment does not exist."),
            "not_resumable": _("Only a paused or failed experiment can be resumed."),
        }
        flash(messages[str(error)], "warning")
        return redirect(url_for("experiments.experiments"))
    except Exception:
        conn.rollback()
        flash(_("The experiment could not be resumed."), "danger")
        return redirect(url_for("experiments.experiments"))
    finally:
        cursor.close()
        conn.close()
    flash(
        _("Experiment resumed. %(processed)s stored result(s) were preserved and %(pending)s URL(s) remain pending.",
          processed=processed, pending=max(0, total - processed)),
        "success",
    )
    if request.form.get("return_to") == "list":
        return redirect(url_for("experiments.experiments"))
    return redirect(url_for("experiments.experiment_report", experiment_id=experiment_id))


@experiments_bp.route("/experiments/<int:experiment_id>/pause", methods=["POST"])
def pause_experiment(experiment_id):
    """Request a cooperative pause without discarding the current dataset."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id,status FROM experiments WHERE id=%s FOR UPDATE",
            (experiment_id,),
        )
        experiment = cursor.fetchone()
        if not experiment:
            raise ValueError("missing")
        if experiment.get("status") not in {"queued", "running"}:
            raise ValueError("not_active")
        cursor.execute(
            "UPDATE experiments SET status='paused', completed_at=NULL WHERE id=%s",
            (experiment_id,),
        )
        conn.commit()
    except ValueError as error:
        conn.rollback()
        messages = {
            "missing": _("The requested evaluation experiment does not exist."),
            "not_active": _("Only a queued or running experiment can be paused."),
        }
        flash(messages[str(error)], "warning")
        return redirect(url_for("experiments.experiments"))
    except Exception:
        conn.rollback()
        flash(_("The experiment could not be paused."), "danger")
        return redirect(url_for("experiments.experiments"))
    finally:
        cursor.close()
        conn.close()
    flash(_("Experiment paused. Stored results and sampling progress were preserved."), "success")
    if request.form.get("return_to") == "list":
        return redirect(url_for("experiments.experiments"))
    return redirect(url_for("experiments.experiment_report", experiment_id=experiment_id))


@experiments_bp.route("/experiments/<int:experiment_id>/delete", methods=["POST"])
def delete_experiment(experiment_id):
    from harness.routes import protect
    protect()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, title, status FROM experiments WHERE id = %s",
        (experiment_id,),
    )
    experiment = cursor.fetchone()

    if not experiment:
        cursor.close()
        conn.close()
        flash(_("The requested evaluation experiment does not exist."), "warning")
        return redirect(url_for("experiments.experiments"))

    if experiment.get("status") in {"queued", "running"}:
        cursor.close()
        conn.close()
        flash(_("Evaluation #%(id)s cannot be deleted while it is queued or running. Wait for it to finish, or pause it from Evaluations and wait for the current page to finish before deleting it.", id=experiment_id), "warning")
        return redirect(url_for("experiments.experiments"))

    try:
        cursor.execute(
            """SELECT COUNT(*) AS total FROM remediation_runs rr
               JOIN experiment_results r ON r.id=rr.source_result_id
               WHERE r.experiment_id=%s""", (experiment_id,),
        )
        dependent_count = int((cursor.fetchone() or {}).get("total") or 0)
        if dependent_count:
            cursor.execute(
                """SELECT rr.id FROM remediation_runs rr
                   JOIN experiment_results r ON r.id=rr.source_result_id
                   WHERE r.experiment_id=%s ORDER BY rr.id LIMIT 10""",
                (experiment_id,),
            )
            ids = ", ".join(f"#{row['id']}" for row in cursor.fetchall())
            if dependent_count > 10:
                ids += ", …"
            flash(_("Evaluation #%(id)s cannot be deleted: %(count)s remediation run(s) use its stored pages (%(runs)s). Find these IDs in Executions. Keep this evaluation if those runs are needed; otherwise delete the dependent runs first. Delete dependent executions before removing their captured sources.", id=experiment_id, count=dependent_count, runs=ids), "warning")
            return redirect(url_for("experiments.experiments"))
        cursor.execute(
            "DELETE FROM experiment_results WHERE experiment_id = %s",
            (experiment_id,),
        )
        cursor.execute(
            "DELETE FROM experiment_environment WHERE experiment_id = %s",
            (experiment_id,),
        )
        cursor.execute("DELETE FROM experiments WHERE id = %s", (experiment_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        current_app.logger.exception("Evaluation %s deletion failed", experiment_id)
        flash(_("Evaluation #%(id)s could not be deleted because the database rejected the operation. The transaction was rolled back. Refresh the list before trying again; if the problem persists, ask the administrator to check the web service logs for this evaluation ID. No generated files were removed.", id=experiment_id), "danger")
        return redirect(url_for("experiments.experiments"))
    finally:
        cursor.close()
        conn.close()

    results_root = os.path.realpath("/results/raw")
    experiment_directory = os.path.realpath(
        os.path.join(results_root, f"experiment_{experiment_id}")
    )
    files_removed = True
    if experiment_directory.startswith(f"{results_root}{os.sep}") and os.path.isdir(experiment_directory):
        try:
            shutil.rmtree(experiment_directory)
        except OSError:
            files_removed = False

    if files_removed:
        flash(_("Evaluation experiment and all associated data were deleted."), "success")
    else:
        flash(
            _("The database records were deleted, but some generated files could not be removed."),
            "warning",
        )
    return redirect(url_for("experiments.experiments"))


@experiments_bp.route("/experiments/<int:experiment_id>/loading", methods=["GET"])
def experiment_report_loading(experiment_id):
    """Keep existing capture links pointed at the current report."""
    return redirect(url_for('experiments.experiment_report', experiment_id=experiment_id))


@experiments_bp.route("/experiments/<int:experiment_id>/raw/<int:result_id>/<tool>", methods=["GET"])
def download_raw_result(experiment_id, result_id, tool):
    allowed_tools = {
        "axe": "axe_raw_path",
        "lighthouse": "lighthouse_raw_path",

        "semantic": "semantic_raw_path",
        "response": "response_source_path",
        "rendered": "source_snapshot_path",
    }

    if tool not in allowed_tools:
        flash(_("Invalid tool requested for download."), "danger")
        return redirect(url_for("experiments.experiment_report", experiment_id=experiment_id))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, experiment_id, url,
               axe_raw_path, lighthouse_raw_path, wave_raw_path, semantic_raw_path,
               response_source_path, source_snapshot_path
        FROM experiment_results
        WHERE id = %s AND experiment_id = %s
    """, (result_id, experiment_id))

    result = cursor.fetchone()

    cursor.close()
    conn.close()

    if not result:
        flash(_("The requested result was not found."), "danger")
        return redirect(url_for("experiments.experiment_report", experiment_id=experiment_id))

    file_path = result.get(allowed_tools[tool])

    allowed_root = os.path.realpath("/results/raw")
    resolved_path = os.path.realpath(file_path) if file_path else ""
    if (
        not resolved_path.startswith(f"{allowed_root}{os.sep}")
        or not os.path.isfile(resolved_path)
    ):
        flash(_("The requested file does not exist or was not generated."), "warning")
        return redirect(url_for("experiments.experiment_report", experiment_id=experiment_id))

    is_html = tool in {"response", "rendered"}
    extension = "html" if is_html else "json"
    filename = f"experiment_{experiment_id}_result_{result_id}_{tool}.{extension}"

    return send_file(
        resolved_path,
        as_attachment=True,
        download_name=filename,
        mimetype="text/html" if is_html else "application/json"
    )


@experiments_bp.route("/experiments/<int:experiment_id>/screenshot/<int:result_id>", methods=["GET"])
def experiment_screenshot(experiment_id, result_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT screenshot_path
        FROM experiment_results
        WHERE id = %s AND experiment_id = %s
        """,
        (result_id, experiment_id),
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    screenshot_path = result.get("screenshot_path") if result else None
    allowed_root = os.path.realpath("/results/raw")
    resolved_path = os.path.realpath(screenshot_path) if screenshot_path else ""
    if (
        not resolved_path.startswith(f"{allowed_root}{os.sep}")
        or not os.path.isfile(resolved_path)
    ):
        return Response(status=404)

    return send_file(resolved_path, mimetype="image/jpeg", conditional=True)


@experiments_bp.get('/experiments/<int:experiment_id>')
def experiment_report(experiment_id):
    from flask import abort
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT * FROM experiments WHERE id=%s', (experiment_id,))
        experiment = cursor.fetchone()
        if experiment is None:
            abort(404)
        cursor.execute('SELECT * FROM experiment_results WHERE experiment_id=%s ORDER BY id', (experiment_id,))
        results = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    from capture_report import details
    summary = details(results, current_app.config.get('HARNESS_ROOT') or os.getenv('HARNESS_ROOT','/data/harness'))
    return render_template('source_report.html', experiment=experiment, results=results, summary=summary)


@experiments_bp.get('/experiments/<int:experiment_id>/source/<int:result_id>')
def source_page(experiment_id, result_id):
    from flask import abort
    from capture_saved_page import page_response
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT * FROM experiment_results WHERE experiment_id=%s AND id=%s', (experiment_id, result_id))
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    if not row:
        abort(404)
    return page_response(row, Path(os.getenv('DATASET_ROOT', '/datasets')))


@experiments_bp.get('/experiments/<int:experiment_id>/source/<int:result_id>/saved/<token>/<path:filename>')
def saved_source_file(experiment_id, result_id, token, filename):
    from capture_saved_page import saved_file
    return saved_file(experiment_id, result_id, token, filename, Path(os.getenv('DATASET_ROOT', '/datasets')))


@experiments_bp.get('/experiments/<int:experiment_id>/csv')
def download_experiment_csv(experiment_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT id,url,status,axe_wcag_violations,lighthouse_score,execution_seconds,evaluated_at FROM experiment_results WHERE experiment_id=%s ORDER BY id', (experiment_id,))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    columns = ['id','url','status','axe_wcag_violations','lighthouse_score','execution_seconds','evaluated_at']
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition':f'attachment; filename=capture-{experiment_id}.csv'})


@experiments_bp.get('/experiments/<int:experiment_id>/json')
def download_experiment_json(experiment_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT id,url,status,axe_wcag_violations,lighthouse_score,execution_seconds,evaluated_at FROM experiment_results WHERE experiment_id=%s ORDER BY id', (experiment_id,))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return Response(json.dumps(rows, default=str), mimetype='application/json', headers={'Content-Disposition':f'attachment; filename=capture-{experiment_id}.json'})
