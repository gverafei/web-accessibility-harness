"""Complete budget-limited censuses without replacing evidence or paid batches."""
from harness.contracts import ContractError

BUDGET_ERRORS = frozenset((
    'Campaign cost limit reached',
    'Insufficient account budget for a bounded request',
    'Request reservation exceeds the per-call cost limit; no HTTP request sent',
))
TIME_ERRORS = frozenset(('Provider account time limit reached',
    'Account deadline elapsed before dispatch',
    'Provider exceeded its recorded deadline; response and charge retained'))
CONFIGURATION_ERRORS = frozenset((
    'Luna light vision configuration must be explicitly available',
))


def assessment_checkpoint(store, providers, ident):
    try:
        original = store.get(ident)
    except KeyError:
        return None, ident, None
    errors = original['data'].get('errors', [])
    if errors:
        try:
            completed = store.get(ident + '-completed')
            if completed['data'].get('completion_parent_assessment_id') != ident:
                raise ContractError('Taxonomy completion parent mismatch')
            return completed, completed['id'], ident
        except KeyError:
            pass
    runtime = providers.manifest.get('runtime_snapshot')
    revisions = store.list('campaign_execution_revision', providers.campaign) if runtime else []
    recovery = next((row for row in reversed(revisions)
                     if row['data'].get('runtime_snapshot') == runtime
                     and row['data'].get('raw_receipts_modified') is False), None)
    configuration_recovery = bool(recovery and errors
                                  and all(error in CONFIGURATION_ERRORS for error in errors))
    authorized_errors = {'Returned model differs from the frozen requested identity',
                         'A shared budget call has unresolved consumption'}
    authorized_errors.update('Provider error ' + str(code) + '; response and billing evidence retained'
                             for code in (408, 429, 500, 502, 503, 504))
    authorized_errors.update('Provider returned HTTP ' + str(code)
                             for code in (408, 429, 500, 502, 503, 504))
    failed_calls = set(original['data'].get('call_ids', []))
    provider_recovery = bool(recovery and errors and set(errors) <= authorized_errors
        and any(row['data']['call_id'] in failed_calls
                for row in store.list('call_retry_authorization', providers.campaign)))
    from harness.time_policy import ITERATION_BOUNDARY
    complete_time = (getattr(providers, 'manifest', {}).get('time_policy') == ITERATION_BOUNDARY
                     and bool(errors) and all(error in TIME_ERRORS for error in errors))
    if not complete_time and not configuration_recovery and not provider_recovery and (not errors or any(error not in BUDGET_ERRORS for error in errors)):
        return original, ident, None
    prior = store.get(original['campaign'])['data']['campaign_cost_limit']
    current = providers.manifest['campaign_cost_limit']
    if not complete_time and not configuration_recovery and not provider_recovery and current <= prior:
        return original, ident, None
    attempt = ident + '-completion-' + (recovery['id'] if configuration_recovery or provider_recovery else providers.campaign)
    try:
        return store.get(attempt), attempt, ident
    except KeyError:
        return None, attempt, ident


def save_assessment(store, providers, ident, parent, data):
    if parent:
        data['completion_parent_assessment_id'] = parent
        if not data.get('errors'):
            ident = parent + '-completed'
    return store.append('taxonomy_assessment', data, providers.campaign, ident)
