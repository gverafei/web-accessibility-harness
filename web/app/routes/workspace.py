"""Task-focused URL submission and its execution status."""
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from harness.store import Store
from harness.routes import protect
from harness.remediation_bridge import options
from harness.decision_models import capture_choices
from remediation_model_choices import model_choices
from remediation_recipes import common_conditions
from settings import get_settings
from database import get_connection
from workspace_pipeline import submission_values, enqueue

workspace_bp = Blueprint('workspace', __name__)


def configuration_options(settings, store):
    return dict(options(store, include_groups=False), verifiers=[v for v in capture_choices(settings) if v.get('vision')])


def submission_record(store, ident):
    from flask import abort
    try:
        record = store.get(ident)
    except KeyError:
        abort(404)
    if record['kind'] != 'url_submission':
        abort(404)
    return record


def submission_progress(store, record):
    state = store.checkpoint(record['id'])[0]
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute('SELECT status FROM experiments WHERE id=%s', (record['data']['experiment_id'],))
        capture = cursor.fetchone() or {}
        cursor.execute("""SELECT rr.id,rr.status FROM remediation_runs rr
            JOIN experiment_results r ON r.id=rr.source_result_id
            WHERE r.experiment_id=%s
              AND JSON_UNQUOTE(JSON_EXTRACT(rr.model_config_json,'$.submission_id'))=%s
            ORDER BY rr.id""", (record['data']['experiment_id'], record['id']))
        runs = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
    destination = None
    if runs and len(record['data']['urls']) == 1:
        destination = url_for('remediation.run_detail', run_id=runs[0]['id'])
    elif runs and (len(runs) >= len(record['data']['urls']) or state.get('runs')):
        destination = url_for('remediation.runs', live_ids=','.join(str(run['id']) for run in runs))
    failed = state.get('status') == 'failed' or capture.get('status') == 'failed'
    message = (_('Capture could not be completed.') if failed else
               _('Preparing remediation…') if capture.get('status') == 'completed' else
               _('Capturing and measuring the page…') if capture.get('status') == 'running' else
               _('Waiting for capture…'))
    phase = ('preparing' if capture.get('status') == 'completed' else
             'capturing' if capture.get('status') == 'running' else 'queued')
    return {'status': 'failed' if failed else state.get('status', 'queued'), 'phase': phase,
            'message': state.get('error') or message, 'runs': runs, 'destination': destination}


@workspace_bp.route('/', methods=['GET', 'POST'])
def launch():
    store = Store(current_app.config.get('HARNESS_ROOT'))
    if request.method == 'GET' and request.args.get('submission'):
        record = submission_record(store, request.args['submission'])
        return redirect(url_for('workspace.preparing', ident=record['id']))
    settings = get_settings()
    available = configuration_options(settings, store)
    if request.method == 'POST':
        protect()
        try:
            configuration = submission_values(request.form, settings, available)
            ident = enqueue(store, configuration, settings, session.get('language', 'es'))
        except ValueError as error:
            flash(_(str(error)), 'danger')
        else:
            return redirect(url_for('workspace.preparing', ident=ident))
    return render_template('workspace.html', models=model_choices(settings),
                           controls=common_conditions(settings), available=available,
                           active_submission=None, form_values=request.form)


@workspace_bp.get('/remediation/preparing/<ident>')
def preparing(ident):
    store = Store(current_app.config.get('HARNESS_ROOT'))
    record = submission_record(store, ident)
    progress = submission_progress(store, record)
    if progress['destination']:
        return redirect(progress['destination'])
    return render_template('remediation_preparing.html', submission=record,
                           progress=progress)


@workspace_bp.get('/sessions/<ident>')
def submission(ident):
    store = Store(current_app.config.get('HARNESS_ROOT'))
    record = submission_record(store, ident)
    state = submission_progress(store, record)
    return redirect(state['destination'] or url_for('workspace.preparing', ident=ident))


@workspace_bp.get('/sessions/<ident>/status')
def submission_status(ident):
    store = Store(current_app.config.get('HARNESS_ROOT'))
    state = submission_progress(store, submission_record(store, ident))
    response = jsonify(state)
    response.headers['Cache-Control']='no-store'
    return response
