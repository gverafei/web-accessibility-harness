"""Explicit runtime amendments at recorded, financially reconciled run boundaries."""
import copy

from .contracts import ContractError, digest
from .providers import Ledger


def create_preparation_revision(store, campaign_id, run_id, runtime, reference, source_admission_id=None):
    """Amend a failed source admission before any repair work has started."""
    campaign = store.get(campaign_id)
    calls = Ledger(store).rows(campaign_id, run_id)
    verifications = [row for row in store.list('evidence_verification', campaign_id)
                     if row['data'].get('phase') == 'baseline']
    admission = {}
    if source_admission_id:
        from .source_admission import validate
        record = validate(store, campaign, run_id, source_admission_id)
        verification = store.get(record['data']['verification_id'])
        if verification['id'] not in {row['id'] for row in verifications}:
            verifications.append(verification)
        admission = {'source_admission_id': record['id'], 'source_admission_hash': record['hash']}
    allowed = {row['id'] + ':agent' for row in verifications}
    revisions = store.list('campaign_execution_revision', campaign_id)
    if (campaign['kind'] != 'campaign' or not reference.strip() or (not calls and not admission)
            or not any(row['data'].get('status') in ('rejected', 'review_required') for row in verifications)
            or store.checkpoint(run_id)[0]
            or any(store.list(kind, campaign_id) for kind in
                   ('page', 'run', 'attempt', 'run_result'))
            or any(not row['data'].get('preparation_only') or row['data']['run_id'] != run_id
                   for row in revisions)
            or any(call['account'] != 'review' or call['logical_key'] not in allowed
                   or call['status'] == 'dispatching'
                   or call['cost_status'] not in ('provider_reported', 'reconciled', 'local')
                   for call in calls)):
        raise ContractError('Preparation recovery requires only reconciled source-admission calls and no repair work')
    previous = (revisions[-1]['data']['runtime_snapshot'] if revisions
                else campaign['data']['runtime_snapshot'])
    manifest = copy.deepcopy(campaign['data'])
    manifest['runtime_snapshot'] = copy.deepcopy(runtime)
    return store.append('campaign_execution_revision', {
        'campaign_id': campaign_id, 'run_id': run_id, 'preparation_only': True,
        'parent_outcome_id': None, 'parent_manifest_hash': campaign['hash'],
        'previous_runtime': previous, 'initial_runtime': campaign['data']['runtime_snapshot'],
        'previous_execution_id': revisions[-1]['id'] if revisions else None, **admission,
        'runtime_snapshot': runtime, 'effective_manifest_hash': digest(manifest),
        'reference': reference, 'prior_call_ids': [call['id'] for call in calls],
        'prior_charges_usd': sum(call['cost'] or 0 for call in calls),
        'source_verification_ids': [row['id'] for row in verifications],
        'prior_attempt_ids': [], 'completed_iteration': 0,
        'prior_generation_runtime_by_call': {}, 'raw_receipts_modified': False,
    }, campaign_id)


def create_revision(store, campaign_id, run_id, runtime, reference):
    campaign = store.get(campaign_id)
    state = store.checkpoint(run_id)[0]
    calls = Ledger(store).rows(campaign_id, run_id)
    from .reports import current_measurements
    parents, _, revisions = current_measurements(
        store, campaign_id, [store.get(run_id + '-result')], list(calls))
    parent = parents[0]
    parent_id = revisions[-1] if revisions else parent['id']
    prior_attempts = parent['data'].get('attempts', [])
    previous_execution = parent['data'].get('execution_revision_id')
    previous_runtime = (store.get(previous_execution)['data']['runtime_snapshot']
                        if previous_execution else campaign['data']['runtime_snapshot'])
    previous_call_runtimes = parent['data'].get('generation_runtime_by_call', {})
    if (campaign['kind'] != 'campaign' or not reference.strip()
            or parent['campaign'] != campaign_id
            or parent['data']['run_id'] != run_id
            or state.get('attempts') != prior_attempts
            or not isinstance(state.get('iteration'), int)
            or not 0 <= state['iteration'] < campaign['data'].get('attempt_limit', 10)
            or any(call['status'] == 'dispatching'
                   or call['cost_status'] not in ('provider_reported', 'reconciled', 'local')
                   for call in calls)):
        raise ContractError('Recovery requires a recorded run boundary with known charges')
    for ident in prior_attempts:
        attempt = store.get(ident)
        if (attempt['kind'] != 'attempt' or attempt['campaign'] != campaign_id
                or attempt['data'].get('run_id') != run_id):
            raise ContractError('Recovery requires intact prior attempt evidence')
    admission = {}
    if previous_execution:
        prior = store.get(previous_execution)['data']
        admission = {key: prior[key] for key in ('source_admission_id', 'source_admission_hash') if key in prior}
    manifest = copy.deepcopy(campaign['data'])
    manifest['runtime_snapshot'] = copy.deepcopy(runtime)
    return store.append('campaign_execution_revision', {
        'campaign_id': campaign_id, 'run_id': run_id, **admission,
        'parent_outcome_id': parent_id, 'parent_manifest_hash': campaign['hash'],
        'previous_runtime': previous_runtime,
        'initial_runtime': campaign['data']['runtime_snapshot'],
        'runtime_snapshot': runtime, 'effective_manifest_hash': digest(manifest),
        'reference': reference, 'prior_call_ids': [call['id'] for call in calls],
        'prior_charges_usd': sum(call['cost'] or 0 for call in calls),
        'prior_attempt_ids': prior_attempts, 'completed_iteration': state['iteration'],
        'prior_generation_runtime_by_call': {
            call['id']: previous_call_runtimes.get(call['id'], previous_runtime['code_digest'])
            for call in calls if ':call:' in call['logical_key']},
        'raw_receipts_modified': False,
    }, campaign_id)


def resolve_manifest(store, campaign, revision_id, runtime, run_id):
    if not revision_id:
        if campaign['data']['runtime_snapshot'] != runtime:
            raise ContractError('Frozen runtime changed; create a new remediation manifest')
        return campaign['data'], None
    revision = store.get(revision_id)
    data = revision['data']
    if (revision['kind'] != 'campaign_execution_revision'
            or revision['campaign'] != campaign['id']
            or data['campaign_id'] != campaign['id'] or data['run_id'] != run_id
            or data['parent_manifest_hash'] != campaign['hash']
            or data.get('initial_runtime', data['previous_runtime']) != campaign['data']['runtime_snapshot']
            or data['runtime_snapshot'] != runtime
            or data['raw_receipts_modified'] is not False):
        raise ContractError('Execution recovery does not match the frozen campaign and runtime')
    if data.get('source_admission_id'):
        from .source_admission import validate
        admission = validate(store, campaign, run_id, data['source_admission_id'])
        if admission['hash'] != data.get('source_admission_hash'):
            raise ContractError('Source eligibility receipt changed')
    manifest = copy.deepcopy(campaign['data'])
    manifest['runtime_snapshot'] = copy.deepcopy(runtime)
    if digest(manifest) != data['effective_manifest_hash']:
        raise ContractError('Execution recovery cannot change strategies, sources, models or limits')
    return manifest, revision


def validate_outcome_revision(store, revision, incumbent, calls):
    data = revision['data']
    execution = store.get(data['execution_revision_id'])
    campaign = store.get(revision['campaign'])
    manifest, _ = resolve_manifest(store, campaign, execution['id'],
                                   execution['data']['runtime_snapshot'], incumbent['run_id'])
    outcome = data['outcome']
    if (data['parent_outcome_id'] != execution['data']['parent_outcome_id']
            or data['raw_receipts_modified'] is not False
            or incumbent.get('attempts', []) != execution['data'].get('prior_attempt_ids', [])
            or outcome['attempts'][:len(incumbent.get('attempts', []))] != incumbent.get('attempts', [])
            or outcome['execution_revision_id'] != execution['id']
            or outcome['generation_runtime_sha256'] != manifest['runtime_snapshot']['code_digest']):
        raise ContractError('Recovered outcome must preserve the interrupted run and prior attempts')
    prior = {call['id']: call for call in calls}
    if not set(execution['data']['prior_call_ids']).issubset(prior):
        raise ContractError('Recovered outcome cannot omit earlier consumption')
    costs = outcome['costs']
    recorded_at = revision.get('created', float('inf'))
    owned = [call for call in calls if call['run'] == incumbent['run_id']
             and call['created'] <= recorded_at]
    if (set(costs['call_ids']) != {call['id'] for call in owned}
            or abs(costs['cost_usd'] - sum(call['cost'] or 0 for call in owned)) > 1e-10):
        raise ContractError('Recovered outcome must include all original and recovery charges')
    selected = outcome['selected']
    source = store.get(selected['source_id'])
    if selected.get('audit_id') is None:
        response_attempt = outcome.get('response_attempt_id') or next(reversed(outcome['attempts']), None)
        if response_attempt is None:
            raise ContractError('Missing page measurements require a recorded response attempt')
        attempt = store.get(response_attempt)['data']
        if (outcome.get('comparison_mode') != 'zero-shot'
                or selected['original'] is not False or source['kind'] != 'artifact'
                or outcome['axe'] is not None or outcome['lighthouse'] is not None
                or attempt['source_id'] != source['id']
                or attempt.get('output_evidence', {}).get('evaluable') is not False):
            raise ContractError('Missing page measurements require an explicit single-pass observation')
        return
    audit = store.get(selected['audit_id'])
    if (audit['kind'] != 'audit' or audit['data']['status'] != 'completed'
            or source['kind'] != 'artifact'
            or outcome['axe'] != audit['data']['axe']
            or outcome['lighthouse'] != audit['data']['lighthouse']):
        raise ContractError('Recovered outcome requires the actual selected source and audit')
    if not selected['original'] and not outcome['attempts']:
        raise ContractError('Recovered candidate requires its recorded repair attempts')


def record_outcome(store, execution_revision, outcome):
    data = {'parent_outcome_id': execution_revision['data']['parent_outcome_id'],
            'execution_revision_id': execution_revision['id'], 'outcome': outcome,
            'raw_receipts_modified': False}
    if data['parent_outcome_id'] is None:
        if not execution_revision['data'].get('preparation_only'):
            raise ContractError('An absent parent requires a recorded pre-generation boundary')
        validate_outcome_revision(store, {'data': data, 'campaign': execution_revision['campaign']},
            {'run_id': execution_revision['data']['run_id'], 'attempts': []},
            Ledger(store).rows(execution_revision['campaign']))
        return store.append('run_result', outcome, execution_revision['campaign'], outcome['run_id'] + '-result')
    parent = store.get(data['parent_outcome_id'])
    parent_data = parent['data'] if parent['kind'] == 'run_result' else parent['data']['outcome']
    record = {'data': data, 'campaign': execution_revision['campaign']}
    validate_outcome_revision(store, record, parent_data,
                              Ledger(store).rows(execution_revision['campaign']))
    ident = outcome['run_id'] + '-recovered-result-' + execution_revision['id']
    try:
        existing = store.get(ident)
    except KeyError:
        return store.append('execution_recovery_result', data, execution_revision['campaign'], ident)
    if existing['data'] != {'schema': 'a11yharness/1', **data}:
        raise ContractError('An existing recovery outcome cannot be overwritten')
    return existing


def reopened_decision_key(store, campaign_id, run_id, iteration, revision, requested_id):
    """Review an explicitly identified premature stop without overwriting its receipt."""
    key = run_id + '-decision-' + str(iteration)
    if requested_id != key:
        return key
    if not revision or revision['kind'] != 'campaign_execution_revision':
        raise ContractError('Reopening a stop requires a recorded execution revision')
    data = revision['data']
    previous = store.get(requested_id)
    if (revision['campaign'] != campaign_id or data['run_id'] != run_id
            or data['completed_iteration'] != iteration
            or previous['kind'] != 'decision' or previous['campaign'] != campaign_id
            or previous['data'].get('run_id') != run_id
            or previous['data'].get('selected') != 'stop'):
        raise ContractError('Only the recorded stopped boundary can receive a fresh review')
    return key + '-reopened-' + revision['id']
