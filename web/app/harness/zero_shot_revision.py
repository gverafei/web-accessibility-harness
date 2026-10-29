"""Receipt-bound correction of prose mistakenly measured as a P0 page."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from remediation_baseline import baseline_candidate
from .contracts import ContractError


def validate_revision(store, revision, incumbent, calls):
    data = revision['data']
    outcome = data['outcome']
    owned = {c['id']: c for c in calls if c['run'] == outcome['run_id']}
    call = owned.get(data.get('response_call_id'))
    if (incumbent.get('comparison_mode') != 'zero-shot' or call is None
            or call['status'] != 'received' or not call.get('response_id')
            or data.get('raw_receipts_modified') is not False
            or data.get('no_generation') is not True):
        raise ContractError('Output correction requires the recorded single-pass response')
    if any(c['status'] == 'dispatching' or c['cost_status'] not in
           ('provider_reported', 'reconciled', 'local') for c in owned.values()):
        raise ContractError('Output correction requires resolved original consumption')
    generators = [c for c in owned.values() if ':call:' in c['logical_key'] and c['status'] == 'received']
    if [c['id'] for c in generators] != [call['id']]:
        raise ContractError('Output correction cannot discard another generated response')
    raw = json.loads(store.read_blob(call['response_id']))['choices'][0]['message'].get('content') or ''
    if not isinstance(raw, str):
        raise ContractError('Output correction requires a textual response')
    candidate, evidence = baseline_candidate(raw, '')
    selected = outcome['selected']
    if (evidence['evaluable'] or candidate != raw
            or store.read_blob(selected['source_id']) != raw.encode()
            or data.get('response_sha256') != hashlib.sha256(raw.encode()).hexdigest()
            or selected.get('original') is not False or selected.get('audit_id') is not None
            or selected.get('case_id') is not None or selected.get('admissible') is not False
            or outcome.get('axe') is not None or outcome.get('lighthouse') is not None
            or outcome.get('source_fidelity', {}).get('retention')
            or outcome.get('taxonomy_measurement', {}).get('status') != 'not_applicable'
            or outcome.get('attempts') != [] or outcome.get('output_evidence', {}).get('evaluable') is not False
            or outcome.get('admissible_success') is not False or outcome.get('preserved_success') is not False):
        raise ContractError('Non-page correction must retain raw prose and unavailable measurements')
    excluded = set(data.get('excluded_call_ids', []))
    if excluded != set(owned) - {call['id']} or call['account'] != 'repair':
        raise ContractError('Only the sole generator charge may remain in the corrected observation')
    if any(c['created'] < call['created'] + call['elapsed'] for ident, c in owned.items() if ident in excluded):
        raise ContractError('Excluded measurement calls must follow the completed response')
    costs = outcome['costs']
    expected = Decimal(str(call['cost'] or 0)).quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP)
    if (costs['call_ids'] != [call['id']] or Decimal(str(costs['cost_usd'])) != expected
            or costs['input_tokens'] != call['input_tokens'] or costs['output_tokens'] != call['output_tokens']):
        raise ContractError('Corrected resources must equal the retained generator receipt')
    archive = store.get(data['sql_archive_id'])['data']
    if not archive.get('artifact_id'):
        raise ContractError('Output correction requires a recoverable SQL archive')
    expected_seconds = call['created'] + call['elapsed'] - archive['run_started_epoch']
    if (abs(outcome['seconds'] - expected_seconds) > .001
            or outcome['seconds'] < call['elapsed'] or outcome['seconds'] > incumbent['seconds']):
        raise ContractError('Corrected time must exclude only work after the response')
