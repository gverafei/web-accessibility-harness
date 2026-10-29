"""Reviewed redundant attempts are excluded from repair counts, never billing."""
from .contracts import ContractError, digest
from .progress_continuation import completed_objective

VERSION = 'reviewed-repair-iterations-v1'


def record_exclusion(store, campaign, run_id, first, redundant, findings,
                     selected_iteration_id, continuation_id):
    if not completed_objective(findings, {'max_axe': 0, 'min_lighthouse': 100}):
        raise ContractError('The first candidate still has measured work remaining')
    if first['iteration_number'] >= redundant['iteration_number']:
        raise ContractError('Exclusion must follow the completed candidate')
    if selected_iteration_id == redundant['id']:
        raise ContractError('A selected endpoint cannot be excluded from analysis')
    payload = {
        'version': VERSION, 'run_id': run_id,
        'first_iteration_id': first['id'],
        'first_iteration_number': first['iteration_number'],
        'first_document_sha256': first['document_sha256'],
        'excluded_iteration_id': redundant['id'],
        'excluded_iteration_number': redundant['iteration_number'],
        'excluded_document_sha256': redundant['document_sha256'],
        'identical_document': first['document_sha256'] == redundant['document_sha256'],
        'continuation_id': continuation_id,
        'reason': 'forced_correction_after_complete_candidate',
        'author_request': 'Exclude unnecessary iterations from the paper repair count.',
        'billing_policy': 'All recorded calls, charges and elapsed time remain in resource totals.',
    }
    ident = 'iteration-exclusion-' + digest(payload)
    try:
        return store.get(ident)
    except KeyError:
        return store.append('iteration_exclusion', payload, campaign, ident)


def exclusions(store, campaign, run_id):
    return [row for row in store.list('iteration_exclusion', campaign)
            if row['data'].get('run_id') == run_id]


def repair_count(raw_count, rows):
    numbers = {row['data']['excluded_iteration_number'] for row in rows}
    if len(numbers) > raw_count:
        raise ContractError('Exclusions exceed the recorded attempt count')
    return raw_count - len(numbers)


def validate_revision(store, revision, incumbent, calls):
    """Accept resource cleanup only with bound raw receipts and fixed endpoints."""
    from decimal import Decimal, ROUND_HALF_UP
    data = revision['data']
    outcome = data['outcome']
    immutable = ('selected', 'axe', 'lighthouse', 'taxonomy_measurement',
                 'source_fidelity', 'candidate_usability', 'admissible_success')
    if any(outcome.get(key) != incumbent.get(key) for key in immutable):
        raise ContractError('Iteration cleanup cannot change the measured endpoint')
    if data.get('raw_receipts_modified') is not False:
        raise ContractError('Provider receipts must remain unchanged')
    excluded = set(data['excluded_call_ids'])
    owned = {call['id']: call for call in calls if call['run'] == outcome['run_id']}
    if not excluded.issubset(owned):
        raise ContractError('Every excluded call requires its original receipt')
    if any(call['cost_status'] in ('unknown', 'reserved', 'estimated')
           or call['status'] == 'dispatching' for call in owned.values()):
        raise ContractError('Unresolved consumption cannot be cleaned up')
    kept = [call for ident, call in owned.items() if ident not in excluded]
    expected = sum((Decimal(str(call['cost'] or 0)) for call in kept), Decimal('0'))
    expected = expected.quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP)
    if Decimal(str(outcome['costs']['cost_usd'])) != expected:
        raise ContractError('Cleaned experiment costs must match included receipts')
    if set(outcome['costs']['call_ids']) != {call['id'] for call in kept}:
        raise ContractError('Cleaned call denominator differs from receipt selection')
    excluded_attempts = set(data['excluded_attempt_ids'])
    if outcome['attempts'] != [ident for ident in incumbent['attempts'] if ident not in excluded_attempts]:
        raise ContractError('Attempt cleanup must preserve every other attempt')
    if not store.get(data['sql_archive_id'])['data'].get('artifact_id'):
        raise ContractError('Cleanup requires a recoverable SQL archive')
