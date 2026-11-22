"""Single-pass comparator using the shared receipt store and post-hoc instruments."""
import hashlib
import json
import time
import uuid
from pathlib import Path

from axe_metrics import candidate_metrics, persist_metrics
from generation_input_projection import compact_repeated_styles
from harness.contracts import MeasurementIncomplete
from harness.engine import once
from remediation_baseline import NAME, PROMPT_VERSION, baseline_candidate, baseline_messages
from remediation_output_budget import FULL_DOCUMENT_OUTPUT_TOKENS


def sole_generation(bridge):
    """A reconciled empty retransmission cannot become a second model proposal."""
    from harness.providers import Ledger
    generation = [call for call in bridge.providers.ledger.rows(bridge.cid, bridge.rid)
                  if ':call:' in call['logical_key']]
    by_key = {call['logical_key']: call for call in generation}
    authorizations = {row['data']['call_id']: row['data']
                      for row in bridge.store.list('call_retry_authorization', bridge.cid)}
    excluded = []
    for call in generation:
        authorization = authorizations.get(call['id'])
        replacement = by_key.get(authorization['retry_key']) if authorization else None
        if (replacement and call.get('cost_status') == 'reconciled' and call.get('cost') == 0
                and Ledger(bridge.store).retryable_failure(call)
                and replacement.get('request_hash') == call.get('request_hash')
                and replacement.get('status') == 'received' and replacement.get('response_id')):
            excluded.append(call['id'])
    completed = [call for call in generation if call['id'] not in excluded]
    if len(completed) != 1:
        raise MeasurementIncomplete('Zero-shot must contain exactly one generator call')
    return completed[0], excluded


def generate(bridge, settings, source, output_dir, model_call):
    """A stable logical call key makes measurement recovery generation-free."""
    if bridge.begin_iteration(1)[0] is None:
        from harness.run_stop import RunStopped
        raise RunStopped()
    projected, projection = compact_repeated_styles(source)
    messages = baseline_messages(projected)
    (output_dir / 'generation-input.html').write_text(projected, encoding='utf-8')
    (output_dir / 'input-projection.json').write_text(json.dumps(projection, indent=2))
    result = model_call(
        settings, bridge.worker['model'], messages[0]['content'],
        messages=messages, json_mode=False, temperature=None,
        reasoning_override=bridge.worker.get('reasoning_effort'),
        output_token_limit=FULL_DOCUMENT_OUTPUT_TOKENS,
    )
    response, incoming, outgoing, cost, seconds, actual = result
    if actual != bridge.worker['model']:
        raise MeasurementIncomplete('Provider response identity differs from the frozen worker')
    (output_dir / 'one-shot-original-response.txt').write_text(response, encoding='utf-8')
    candidate, evidence = baseline_candidate(response, source, bridge.url)
    evidence.update(input_projection=projection, generation_calls=1,
                    response_sha256=hashlib.sha256(response.encode()).hexdigest())
    (output_dir / 'baseline-output.json').write_text(json.dumps(evidence, indent=2))
    return candidate, evidence, result


def no_page_outcome(bridge, candidate, evidence):
    """Missing page metrics are explicit; an observed response is never the source."""
    blob = bridge.store.blob(candidate, 'zero_shot_output', bridge.cid, 'text/plain')
    attempt = once(bridge.store, 'attempt', {
        'run_id': bridge.rid, 'source_id': blob['id'], 'audit_id': None,
        'retained': True, 'output_evidence': evidence,
        'seconds': time.time() - bridge.attempt_started,
    }, bridge.cid, bridge.attempt_id)
    selected = {'source_id': blob['id'], 'audit_id': None, 'original': False,
                'distance': None, 'technical': 'not_applicable', 'admissible': False}
    bridge.state.update(incumbent=selected, iteration=1, attempts=[], status='completed')
    bridge.persist()
    outcome = {
        'run_id': bridge.rid, 'page_id': bridge.page['id'], 'condition_id': 'zero-shot',
        'selected': selected, 'axe': None, 'lighthouse': None,
        'taxonomy_measurement': {'status': 'not_applicable', 'reason': evidence['output']},
        'attempts': [], 'response_attempt_id': attempt['id'],
        'seconds': time.time() - bridge.state['started'],
        'costs': bridge.costs(), 'comparison_mode': 'zero-shot', 'output_evidence': evidence,
        'output_policy': 'record-one-output-without-rejection-or-refinement',
        'preserved_success': False, 'admissible_success': False,
        'preservation': 'unverified', 'distance': None,
        'stop_reason': evidence['output'],
    }
    revision = getattr(bridge, 'execution_revision', None)
    if revision:
        from harness.execution_recovery import record_outcome
        outcome.update(execution_revision_id=revision['id'],
            generation_runtime_sha256=bridge.manifest['runtime_snapshot']['code_digest'],
            generation_runtime_by_call=revision['data']['prior_generation_runtime_by_call'])
        record_outcome(bridge.store, revision, outcome)
    else:
        once(bridge.store, 'run_result', outcome, bridge.cid, bridge.rid + '-result')
    bridge.store.checkpoint(bridge.cid, {'status': 'completed', 'stage': 'analysis',
                                      'pages': [bridge.page['id']], 'runs': [bridge.rid]})
    return outcome


def measure_output(bridge, settings, run, source, output_dir, model_call):
    """Persist one observed output, independently of its quality or audit score."""
    candidate, evidence, usage = generate(bridge, settings, source, output_dir, model_call)
    response, incoming, outgoing, generation_cost, generation_seconds, actual = usage
    path = output_dir / ('candidate.html' if evidence['evaluable'] else 'response.txt')
    path.write_text(candidate, encoding='utf-8')
    url = f'http://dataset-server:8080/remediations/{run["id"]}/{path.name}'
    item = {}
    if evidence['evaluable']:
        audit_id = bridge.attempt_id + '-audit'
        try:
            audit = bridge.store.get(audit_id)
        except KeyError:
            audit = bridge.environment.audit(bridge.capture, candidate, bridge.cid,
                                              audit_id, bridge.manifest['evaluator'])
        if audit['data'].get('status') != 'completed':
            error = str(audit['data'].get('error') or audit['data'])
            if 'NO_FCP' not in error and 'NO_PAINT' not in error:
                raise MeasurementIncomplete('Zero-shot audit unavailable: ' + error)
            evidence.update(evaluable=False, output='HTML retained; browser produced no measurable paint',
                            audit_id=audit_id, render_error=error)
        else:
            item = bridge.evaluate({'urls': [url]})
            bridge.outcome(candidate, True)
    outcome = (bridge.finish('One generation response recorded; no refinement') if evidence['evaluable']
               else no_page_outcome(bridge, candidate, evidence))
    return candidate, evidence, usage, path, url, item, outcome


def persist_observation(bridge, settings, run, output_dir, cursor, connection, now, observation):
    candidate, evidence, usage, path, url, item, outcome = observation
    response, incoming, outgoing, generation_cost, generation_seconds, actual = usage
    costs = outcome['costs']
    measurements = candidate_metrics(item['axe']) if item else None
    retention = (outcome.get('source_fidelity') or {}).get('retention', {})
    call, failed_transmissions = sole_generation(bridge)
    if failed_transmissions:
        evidence['empty_transport_call_ids'] = failed_transmissions
    saved = json.loads(bridge.store.read_blob(call['response_id'])) if call['response_id'] else {}
    evidence.update(call_id=call['id'], response_id=call['response_id'],
                    finish_reason=(saved.get('choices') or [{}])[0].get('finish_reason'))
    strategy = {
        'representation': 'single-pass HTML response', 'repair_engine': NAME,
        'baseline': evidence, 'model_configuration': json.loads(run['model_config_json']),
        'measured_candidate': bool(evidence['evaluable'] and measurements),
        'approach': {'name': NAME, 'engine': 'single_shot', 'reproduction': False},
        'content_retention': retention, 'rag': {'enabled': False},
        'context_policy': {'version': PROMPT_VERSION, 'history_replayed': False},
        'candidate_selection': {'policy': 'Retain the sole model output without ranking or rejection'},
        'harness': {'retained': True, 'original_retained': False,
                    'assessment': getattr(bridge, 'assessment', {}), 'consumption': costs},
        'stage_accounting': {
            'generation': {'seconds': generation_seconds, 'cost_usd': generation_cost, 'llm_calls': 1},
            'posthoc_evaluation': {'seconds': max(0, outcome['seconds'] - generation_seconds),
                'cost_usd': costs['cost_usd'] - generation_cost,
                'llm_calls': len(costs['call_ids']) - 1 - sum(ident in costs['call_ids'] for ident in failed_transmissions)},
        },
    }
    previous = None
    if call['response_id']:
        cursor.execute('SELECT id FROM remediation_iterations WHERE run_id=%s AND iteration_number=1', (run['id'],))
        previous = cursor.fetchone()
    if not call['response_id']:
        iteration_id = None
    elif previous:
        iteration_id = previous['id']
        cursor.execute('UPDATE remediation_iterations SET strategy_json=%s WHERE id=%s',
                       (json.dumps(strategy), iteration_id))
        if not evidence['evaluable']:
            cursor.execute('UPDATE remediation_iterations SET output_path=%s,output_url=%s,'
                           'axe_violations=NULL,axe_wcag_violations=NULL,axe_best_practice_issues=NULL,'
                           'axe_metrics_json=NULL,axe_raw_path=NULL,lighthouse_score=NULL,'
                           'screenshot_path=NULL,dom_distance=NULL,original_dom_nodes=NULL,candidate_dom_nodes=NULL,'
                           'dom_changes_json=NULL,specialist_reviews_json=NULL,candidate_key=%s,'
                           'execution_seconds=%s WHERE id=%s',
                           (str(path), url, str(uuid.UUID(hashlib.sha256(candidate.encode()).hexdigest()[:32])),
                            outcome['seconds'], iteration_id))
    else:
        fields = {
            'run_id': run['id'], 'iteration_number': 1, 'prompt_text': baseline_messages(
                (output_dir / 'generation-input.html').read_text())[0]['content'],
            'feedback_text': '', 'output_path': str(path), 'output_url': url,
            'decision': 'accept', 'decision_reason': 'Sole zero-shot output retained for comparison',
            'generator_provider': actual.split('/')[0], 'generator_model': actual,
            'reviewer_provider': 'system', 'reviewer_model': 'system/measurement-only',
            'input_tokens': incoming, 'output_tokens': outgoing, 'cost_usd': generation_cost,
            'execution_seconds': outcome['seconds'],
            'axe_violations': measurements['axe_combined_violations'] if measurements else None,
            'lighthouse_score': outcome['lighthouse'], 'screenshot_path': item.get('screenshot_path'),
            'candidate_key': str(uuid.UUID(hashlib.sha256(candidate.encode()).hexdigest()[:32])),
            'strategy_json': json.dumps(strategy), 'agent_usage_json': json.dumps([
                {'role': 'Generator', 'model': actual, 'input_tokens': incoming,
                 'output_tokens': outgoing, 'cost_usd': generation_cost, 'seconds': generation_seconds,
                 'reasoning_effort': bridge.worker.get('reasoning_effort')}]),
            'created_at': now(settings),
        }
        cursor.execute('INSERT INTO remediation_iterations (' + ','.join(fields) + ') VALUES ('
                       + ','.join(['%s'] * len(fields)) + ')', tuple(fields.values()))
        iteration_id = cursor.lastrowid
    if measurements:
        persist_metrics(cursor, 'remediation_iterations', iteration_id, measurements, item['axe'].get('raw_path'))
    status = 'accepted' if outcome.get('admissible_success') else 'completed_with_warnings'
    progress = ('Zero-shot output recorded; one generation, no refinement' if call['response_id']
                else 'Provider response unavailable after transport failure; measurements unavailable')
    from harness.run_stop import requested
    if requested(bridge.store, run['id']):
        status = 'stopped'
        progress = 'Stopped by user. Recorded results and charges were preserved.'
    cursor.execute("""UPDATE remediation_runs SET status=%s,current_phase='complete',progress_percent=100,
        progress_message=%s,progress_updated_at=%s,current_iteration=%s,accepted_iteration_id=%s,
        total_input_tokens=%s,total_output_tokens=%s,total_cost_usd=%s,execution_seconds=%s,
        completed_at=%s,error_message=NULL,harness_outcome_json=%s WHERE id=%s""",
        (status, progress, now(settings), 1 if call['response_id'] else 0, iteration_id,
         costs['input_tokens'], costs['output_tokens'], costs['cost_usd'], outcome['seconds'],
         now(settings), json.dumps(outcome), run['id']))
    connection.commit()
    (output_dir / 'baseline-output.json').write_text(json.dumps(evidence, indent=2))
    return outcome



def execute(bridge, settings, run, source, output_dir, cursor, connection, model_call, now):
    """Retry persistence from a completed observation without any model activity."""
    unavailable = bridge.store.list('provider_completion_unavailable', bridge.cid)
    if unavailable:
        calls = [c for c in bridge.providers.ledger.rows(bridge.cid, bridge.rid)
                 if ':call:' in c['logical_key']]
        if len(calls) != 1 or unavailable[-1]['data']['call_id'] != calls[0]['id']:
            raise MeasurementIncomplete('Unavailable response does not match the sole generation')
        bridge.begin_iteration(1)
        call = calls[0]
        evidence = {'evaluable':False, 'output':'Provider completion unavailable after transport failure',
                    'generation_calls':1, 'response_received':False,
                    'unavailable_completion_id':unavailable[-1]['id']}
        path = output_dir / 'response.txt'
        path.write_text('', encoding='utf-8')
        outcome = no_page_outcome(bridge, '', evidence)
        usage = ('', call['input_tokens'], call['output_tokens'], call['cost'], call['elapsed'], call['model'])
        observation = ('', evidence, usage, path,
            f'http://dataset-server:8080/remediations/{run["id"]}/response.txt', {}, outcome)
        return persist_observation(bridge, settings, run, output_dir, cursor, connection, now, observation)
    try:
        saved = bridge.store.get(bridge.rid + '-result')
    except KeyError:
        saved = None
    measured_candidate = bool(saved and saved['data'].get('selected', {}).get('original') is False)
    resume_measurement = bool(measured_candidate
        and getattr(bridge, 'execution_revision', None)
        and bridge.state.get('status') == 'failed'
        and bridge.state.get('iteration') == 1
        and len(bridge.state.get('attempts', [])) == 1
        and bridge.state['attempts'] == saved['data'].get('attempts')
        and bridge.state.get('incumbent') == saved['data']['selected']
        and saved['data'].get('taxonomy_measurement', {}).get('status') != 'completed')
    if measured_candidate and (bridge.state.get('status') == 'completed' or resume_measurement):
        # The sole candidate and audit already exist. Retry only its unfinished
        # post-hoc measurement; neither generation nor attempt recording repeats.
        if resume_measurement:
            sole_generation(bridge)
        outcome = (bridge.finish('One generation response recorded; no refinement')
                   if resume_measurement else dict(saved['data']))
        evidence = json.loads((output_dir / 'baseline-output.json').read_text())
        candidate = bridge.store.read_blob(outcome['selected']['source_id']).decode()
        path = output_dir / ('candidate.html' if evidence['evaluable'] else 'response.txt')
        bridge.worker = next(w for w in bridge.manifest['workers']
                             if w['id'] == bridge.condition['worker_id'])
        call, _ = sole_generation(bridge)
        response = (output_dir / 'one-shot-original-response.txt').read_text()
        usage = (response, call['input_tokens'], call['output_tokens'], call['cost'],
                 call['elapsed'], call['model'])
        item = (bridge.store.get(outcome['selected']['audit_id'])['data']['raw_result']
                if outcome['selected']['audit_id'] else {})
        revision = getattr(bridge, 'execution_revision', None)
        if revision and not resume_measurement:
            from harness.execution_recovery import record_outcome
            outcome.update(execution_revision_id=revision['id'],
                generation_runtime_sha256=bridge.manifest['runtime_snapshot']['code_digest'],
                generation_runtime_by_call=revision['data']['prior_generation_runtime_by_call'])
            record_outcome(bridge.store, revision, outcome)
        observation = (candidate, evidence, usage, path,
            f'http://dataset-server:8080/remediations/{run["id"]}/{path.name}', item, outcome)
    else:
        observation = measure_output(bridge, settings, run, source, output_dir, model_call)
    return persist_observation(bridge, settings, run, output_dir, cursor, connection, now, observation)
