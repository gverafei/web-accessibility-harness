"""Explicit spending increases preserve frozen manifests and cumulative charges."""
import copy

from .contracts import ContractError, digest
from .preparation import budget_group, compatible_groups


def effective_group(group, amendments):
    current = copy.deepcopy(group)
    for record in amendments:
        data = record['data']
        if data['group_id'] != group['id']:
            continue
        previous, updated = data['previous'], data['updated']
        if not compatible_groups(previous, current):
            raise ContractError('Budget increases require an intact amendment chain')
        validated = budget_group(dict(updated, stage=group['stage']))
        if (updated['id'] != group['id'] or not data.get('authorization_reference')
                or data.get('reset_spending') is not False
                or validated['total_usd'] <= current['total_usd']
                or set(validated['stage_limits']) != set(current['stage_limits'])
                or any(validated['stage_limits'][key] < value
                       for key, value in current['stage_limits'].items())):
            raise ContractError('Budget increase cannot reset spending or remove existing stage limits')
        current = validated
    return current


def record_increase(store, group_id, total_usd, stage_limits, authorization_reference):
    """Administrative operation; never exposed as a model-callable tool."""
    groups = [row['data']['budget_group'] for kind in ('campaign', 'billing_archive')
              for row in store.list(kind)
              if (row['data'].get('budget_group') or {}).get('id') == group_id]
    if not groups or any(not compatible_groups(groups[0], group) for group in groups):
        raise ContractError('Select an existing consistently frozen shared budget')
    current = effective_group(groups[0], store.list('shared_budget_amendment'))
    updated = budget_group(dict(current, total_usd=total_usd, stage_limits=stage_limits))
    payload = {'group_id': group_id, 'previous': current, 'updated': updated,
               'authorization_reference': authorization_reference, 'reset_spending': False}
    effective_group(current, [{'data': payload}])
    ident = 'shared-budget-increase-' + digest(payload)
    return store.append('shared_budget_amendment', payload, ident=ident)
