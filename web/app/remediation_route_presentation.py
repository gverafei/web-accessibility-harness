"""Read-only strategy traces from evaluated pages and recorded controller choices."""
from remediation_interventions import POLICIES, four_policy, policy_identifier


def strategy_label(run, strategy=None):
    if run.get('execution_mode') == 'single_shot':
        return 'P0'
    strategy = strategy or {}
    version = strategy.get('intervention_version') or run.get('intervention_version')
    level = (strategy.get('approach') or {}).get('public_level')
    if level is None:
        level = strategy.get('assigned_level', strategy.get('public_level'))
    if str(level).isdigit():
        level = int(level)
        if four_policy(version) and 1 <= level <= 4:
            return f'P{level}'
        if not four_policy(version) and 1 <= level <= 6:
            return f'legacy-{level}'
    return None if run.get('dynamic_level') else policy_identifier(run)


def strategy_name(label, strategy=None):
    if label == 'P0':
        return 'Zero-shot'
    if label in {'P1', 'P2', 'P3', 'P4'}:
        return POLICIES[int(label[1:]) - 1].name
    return ((strategy or {}).get('approach') or {}).get('name')


def execution_route(run, iterations, decisions=()):
    steps = []
    for item in iterations:
        strategy = item.get('strategy') or {}
        label = strategy_label(run, strategy)
        steps.append({'id': item['id'],
                      'iteration': item.get('display_iteration_number', item['iteration_number']),
                      'policy': label, 'name': strategy_name(label, strategy),
                      'model': item.get('generator_model'),
                      'retained': item['id'] == run.get('accepted_iteration_id')})
    active = strategy_label(run)
    if run.get('dynamic_level'):
        recorded = [row['data'] for row in decisions
                    if row['data'].get('run_id') == f'sql-run-{run["id"]}'
                    and row['data'].get('selected') not in (None, 'stop')]
        if recorded:
            latest = max(recorded, key=lambda row: row.get('iteration', -1))
            descriptor = next((item for item in latest.get('action_descriptors', [])
                               if item.get('id') == latest['selected']), {})
            active = strategy_label(run, {'public_level': descriptor.get('level')})
        elif steps:
            active = steps[-1]['policy']
    return {'policy': policy_identifier(run), 'steps': steps, 'active': active,
            'labels': {step['id']: step['policy'] for step in steps}}
