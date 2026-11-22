"""URL capture and remediation submissions with restart-safe run identities."""
import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from werkzeug.datastructures import MultiDict
from database import get_connection
from harness.contracts import public_url, number
from harness.store import Store
from remediation_interventions import VERSION
from remediation_model_choices import model_choice
from remediation_recipes import common_conditions
from settings import get_settings


TERMINAL = {'completed', 'failed', 'completed_with_warnings'}
FROZEN_SETTINGS = ('remediation_model_catalog_json', 'decision_model_catalog_json',
                   'generative_model_metadata_json', 'decisions_model_metadata_json',
                   'ollama_base_url', 'ollama_model', 'ollama_capabilities_json')
MAX_CAPTURE_NAME = 160


def submission_values(form, settings, available):
    capture_name = form.get('capture_name', '').strip()
    if len(capture_name) > MAX_CAPTURE_NAME:
        raise ValueError('Use a capture name of at most 160 characters.')
    urls = []
    for line in form.get('urls', '').splitlines():
        line = line.strip()
        if not line:
            continue
        if '://' not in line and re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', line):
            raise ValueError('Use HTTP(S) URLs without embedded credentials.')
        url = public_url(line if '://' in line else 'https://' + line)
        if url not in urls:
            urls.append(url)
    if not urls:
        raise ValueError('Enter at least one HTTP(S) URL.')
    policy = form.get('strategy', 'P2')
    if policy not in {'P0','P1','P2','P3','P4','P5'}:
        raise ValueError('Choose a valid intervention strategy.')
    choice = model_choice(form.get('selected_model', ''), settings)
    cost = number(form.get('max_cost_usd'), 'Budget per URL', 0.001, 5)
    seconds = number(form.get('max_execution_seconds'), 'Time per URL', 30, 7200, True)
    iterations = number(form.get('max_iterations'), 'Maximum iterations', 1, 10, True)
    attempts = number(form.get('max_generation_attempts_per_candidate', 20),
                      'Attempts per candidate', 1, 1000, True)
    axe = number(form.get('max_axe', 5), 'Axe target', 0, 2147483647, True)
    lighthouse = number(form.get('min_lighthouse', 90), 'Lighthouse target', 0, 100, True)
    corpus = form.get('harness_corpus')
    if corpus not in {row['id'] for row in available['corpora']}:
        raise ValueError('Select an available frozen ACT corpus.')
    verifier = form.get('harness_verifier')
    if verifier not in {row['id'] for row in available['verifiers']}:
        raise ValueError('Select an available capture verification model.')
    values = {'selected_model':choice['id'], 'preservation_level':str(max(0,int(policy[1:])-1)),
              'intervention_version':VERSION, 'run_limits_configured':'1',
              'harness_enabled':'1', 'harness_selector':'decisions',
              'max_cost_usd':str(cost), 'max_execution_seconds':str(seconds),
              'max_iterations':str(iterations), 'max_axe':str(axe),
              'max_generation_attempts_per_candidate':str(attempts),
              'min_lighthouse':str(lighthouse), 'harness_corpus':corpus,
              'harness_verifier':verifier, 'execution_mode':'single_shot' if policy=='P0' else 'iterative',
              'act_grounding_configured':'1', 'act_grounding':'on' if form.get('act_grounding') else 'off',
              'rag_top_k':'4', 'harness_max_call_cost_usd':str(cost)}
    return {'urls':urls, 'capture_name':capture_name, 'strategy':policy, 'values':values,
            'reuse_cached_results':form.get('reuse_cached_results') == 'on',
            'settings':{key:settings.get(key,'') for key in FROZEN_SETTINGS}}


def enqueue(store, configuration, settings, language):
    from result_portability import evaluation_signature
    ident = uuid.uuid4().hex
    values = configuration['values']
    total = round(len(configuration['urls']) * float(values['max_cost_usd']), 8)
    group = {'id':'workspace-'+ident, 'stage':'remediation', 'total_usd':total,
             'stage_limits':{'remediation':total}}
    values = dict(values, submission_id=ident, harness_study_id='workspace-'+ident,
                  harness_budget_json=json.dumps(group))
    created = datetime.now(ZoneInfo(settings['app_timezone'])).replace(tzinfo=None)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""INSERT INTO experiments
            (title,urls,include_semantic,include_wave,axe_standard,axe_include_best_practices,
             reuse_cached_results,evaluation_signature,experiment_origin,source_type,
             resource_policy,language,status,created_at)
            VALUES (%s,%s,0,0,%s,%s,%s,%s,'evaluation','url','external',%s,'queued',%s)""",
            (configuration.get('capture_name') or 'Capture '+ident[:8], '\n'.join(configuration['urls']), settings['axe_standard'],
             settings.get('axe_include_best_practices')=='true',
             configuration.get('reuse_cached_results',False),
             evaluation_signature(settings,False,False,None,None,settings['axe_standard']), language, created))
        experiment_id = cursor.lastrowid
        store.append('url_submission', dict(configuration, values=values, experiment_id=experiment_id), ident=ident)
        store.checkpoint(ident, {'status':'queued', 'experiment_id':experiment_id, 'runs':[]})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
    return ident


def advance(store, ident, settings):
    submission = store.get(ident)['data']
    state, revision = store.checkpoint(ident)
    if state.get('status') in TERMINAL:
        return False
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT status FROM experiments WHERE id=%s', (submission['experiment_id'],))
        experiment = cursor.fetchone()
        if not experiment or experiment['status'] not in {'completed','failed'}:
            return False
        cursor.execute('SELECT * FROM experiment_results WHERE experiment_id=%s ORDER BY id', (submission['experiment_id'],))
        sources = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    from remediation_submission import create_remediation
    frozen_settings = dict(settings, **submission['settings'])
    for source in sources:
        if source['status'] != 'completed':
            continue
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM remediation_runs WHERE source_result_id=%s AND JSON_UNQUOTE(JSON_EXTRACT(model_config_json,'$.submission_id'))=%s", (source['id'],ident))
            existing = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()
        if not existing:
            values = dict(submission['values'], source_result_id=str(source['id']))
            create_remediation(MultiDict(values), frozen_settings)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id,status FROM remediation_runs WHERE JSON_UNQUOTE(JSON_EXTRACT(model_config_json,'$.submission_id'))=%s ORDER BY id", (ident,))
        runs = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    active = any(row['status'] in {'queued','running'} for row in runs)
    failed = any(row['status']=='failed' for row in sources+runs)
    status = 'remediating' if active else ('completed_with_warnings' if failed else 'completed')
    if not runs:
        status = 'failed'
    store.checkpoint(ident, {'status':status,'experiment_id':submission['experiment_id'],'runs':runs}, revision)
    return True


def tick(store, settings):
    for row in store.list('url_submission'):
        state, _ = store.checkpoint(row['id'])
        if state.get('status') in TERMINAL:
            continue
        with store.named_lock('url-submission-'+row['id']):
            try:
                if advance(store,row['id'],settings):
                    return True
            except Exception as error:
                store.checkpoint(row['id'], dict(state,status='failed',error=str(error)))
                raise
    return False
