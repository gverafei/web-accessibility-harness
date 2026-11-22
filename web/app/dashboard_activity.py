"""Small read-only dashboard projections from selected SQL measurements."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from remediation_interventions import policy_identifier
from remediation_approaches import dynamic_presentation
from remediation_listing import CampaignReader
from remediation_model_choices import run_model_presentation

COLORS = ('#215F97', '#7050A8', '#B87316', '#218A79', '#BE4D6D')
STRATEGY_COLORS = dict(zip(('P0', 'P1', 'P2', 'P3', 'P4', 'P5'),
                         ('#667085', '#215F97', '#218A79', '#7050A8', '#B87316', '#C13C83')))
TERMINAL = {'accepted', 'completed_with_warnings'}


def number(value):
    return None if value is None else float(value)


def average(values):
    available = [float(value) for value in values if value is not None]
    return sum(available) / len(available) if available else None


def parse_json(value):
    try:
        return json.loads(value or '{}') or {}
    except (TypeError, ValueError):
        return {}


def read_rows(cursor):
    cursor.execute('''SELECT e.id,e.created_at,e.status,
        COALESCE(SUM(r.execution_seconds),0) seconds,
        COUNT(CASE WHEN r.status='completed' THEN 1 END) pages,
        COUNT(CASE WHEN r.status='completed' THEN r.axe_wcag_violations END) axe_n,
        COUNT(CASE WHEN r.status='completed' THEN r.lighthouse_score END) lighthouse_n,
        AVG(CASE WHEN r.status='completed' THEN r.axe_wcag_violations END) axe,
        AVG(CASE WHEN r.status='completed' THEN r.lighthouse_score END) lighthouse,
        COALESCE(SUM(r.cost_incurred_usd),0) cost
        FROM experiments e LEFT JOIN experiment_results r ON r.experiment_id=e.id
        GROUP BY e.id ORDER BY e.created_at,e.id''')
    evaluations = cursor.fetchall()
    cursor.execute('''SELECT rr.id,rr.source_result_id,rr.created_at,rr.status,
        rr.generator_model,rr.model_cost_tier,rr.model_config_json,
        rr.execution_mode,rr.accessibility_priority,rr.intervention_version,rr.harness_config_json,
        rr.total_input_tokens,rr.total_output_tokens,rr.execution_seconds seconds,
        CASE WHEN rr.import_provenance_json IS NULL THEN rr.total_cost_usd ELSE 0 END cost,
        COALESCE(rr.baseline_axe,source.axe_wcag_violations) original_axe,
        selected.axe_wcag_violations axe,selected.lighthouse_score lighthouse,
        (SELECT COUNT(*) FROM remediation_iterations ri WHERE ri.run_id=rr.id
         AND ri.axe_wcag_violations IS NOT NULL AND ri.lighthouse_score IS NOT NULL) iterations,
        JSON_EXTRACT(rr.harness_outcome_json,'$.source_fidelity.retention') retention_json
        FROM remediation_runs rr
        JOIN experiment_results source ON source.id=rr.source_result_id
        LEFT JOIN remediation_iterations selected ON selected.id=rr.accepted_iteration_id
        ORDER BY rr.created_at,rr.id''')
    return evaluations, cursor.fetchall()




def build_activity(evaluations, runs, arguments, now):
    period = str(arguments.get('period', 'all'))
    if period not in ('7', '30', '90', 'all'):
        period = 'all'
    since = None if period == 'all' else now - timedelta(days=int(period))
    profiles = {}
    prepared = []
    for run in runs:
        model = run_model_presentation(run)
        policy = policy_identifier(run) or '?'
        identity = (None if policy == 'P5' else
                    run['generator_model'] + ':' + (model['reasoning_effort'] or 'fixed'))
        # P5 belongs only to the strategy view. Its complete resources cannot be
        # attributed to the last selected worker, or presented as another model.
        if identity is not None and identity not in profiles:
            family = run['generator_model'].split('/')[-1]
            label = ('Luna' if 'gpt-6-luna' == family else 'Haiku' if 'claude-haiku' in family else model['label'] or family)
            effort = model['reasoning_effort']
            if effort:
                label += ' ' + ('light' if effort == 'low' else effort)
            color = '#7050A8' if 'Luna high' == label else '#215F97' if label.startswith('Luna') else '#B87316' if label.startswith('Haiku') else model.get('color') or COLORS[len(profiles) % len(COLORS)]
            profiles[identity] = dict(id=identity, label=label, color=color)
        retention = parse_json(run.get('retention_json'))
        components = [number(retention.get(key)) for key in ('text_percent', 'links_percent', 'images_percent')]
        content = average(components) if all(value is not None for value in components) else None
        prepared.append(dict(id=run['id'], source=run['source_result_id'],
            created=run['created_at'], status=run['status'], profile=identity, policy=policy,
            cost=number(run.get('cost')) or 0, seconds=number(run.get('seconds')) or 0,
            axe=number(run.get('axe')), lighthouse=number(run.get('lighthouse')),
            original_axe=number(run.get('original_axe')), content=content,
            iterations=int(run.get('iterations') or 0),
            input_tokens=int(run.get('total_input_tokens') or 0),
            output_tokens=int(run.get('total_output_tokens') or 0),
            tokens=int(run.get('total_input_tokens') or 0)+int(run.get('total_output_tokens') or 0)))
    selected_model = str(arguments.get('model', ''))
    if selected_model not in profiles:
        selected_model = ''
    policies = sorted({row['policy'] for row in prepared})
    selected_policy = str(arguments.get('policy', ''))
    if selected_policy not in policies:
        selected_policy = ''
    selected_status = str(arguments.get('status', ''))
    if selected_status not in ('accepted', 'completed_with_warnings', 'failed', 'queued', 'running'):
        selected_status = ''
    chosen = [row for row in prepared if (since is None or row['created'] >= since)
              and (not selected_model or row['profile'] == selected_model)
              and (not selected_policy or row['policy'] == selected_policy)
              and (not selected_status or row['status'] == selected_status)]
    evals = [row for row in evaluations if since is None
             or row['created_at'] is not None and row['created_at'] >= since]
    completed = [row for row in chosen if row['status'] in TERMINAL]
    # Source-page averages weight source pages, not experiment-level means.
    measured_evals = [row for row in evals if row['pages']]
    page_count = sum(row['pages'] for row in measured_evals)
    def weighted(field):
        denominator = sum(row[field+'_n'] for row in measured_evals)
        return (sum(float(row[field]) * row[field+'_n'] for row in measured_evals
                    if row[field] is not None) / denominator) if denominator else None
    totals = dict(evaluations=len(evals), evaluation_pages=page_count,
        evaluation_axe=weighted('axe'), evaluation_lighthouse=weighted('lighthouse'),
        runs=len(chosen), completed=len(completed), active=sum(row['status'] in ('queued','running') for row in chosen),
        axe=average(row['axe'] for row in completed), lighthouse=average(row['lighthouse'] for row in completed),
        content=average(row['content'] for row in completed),
        seconds=sum(row['seconds'] for row in chosen)+sum(float(row['seconds'] or 0) for row in evals),
        evaluation_cost=sum(float(row['cost'] or 0) for row in evals),
        remediation_cost=sum(row['cost'] for row in chosen), tokens=sum(row['tokens'] for row in chosen))
    totals['cost'] = totals['evaluation_cost'] + totals['remediation_cost']
    dates = [row['created'] for row in chosen] + [row['created_at'] for row in evals if row['created_at'] is not None]
    start = since or min(dates, default=now)
    hourly = now - start <= timedelta(days=3)
    bucket = (lambda value:value.strftime('%Y-%m-%d %H:00')) if hourly else (lambda value:value.strftime('%Y-%m-%d'))
    tick = start.replace(minute=0, second=0, microsecond=0) if hourly else start.replace(hour=0, minute=0, second=0, microsecond=0)
    interval = timedelta(hours=1) if hourly else timedelta(days=1)
    buckets = []
    while tick <= now:
        buckets.append(bucket(tick))
        tick += interval
    def timeline(groups, dimension):
        series = []
        for group in groups:
            grouped = defaultdict(list)
            for row in chosen:
                if row[dimension] == group['id']:
                    grouped[bucket(row['created'])].append(row)
            series.append({**group,
                'runs': [len(grouped[date]) for date in buckets],
                **{field: [sum(row[field] for row in grouped[date]) for date in buckets]
                   for field in ('cost', 'iterations', 'tokens', 'input_tokens', 'output_tokens')}})
        return dict(labels=buckets, hourly=hourly, series=series)
    ranks = []
    for key, profile in profiles.items():
        group = [row for row in chosen if row['profile'] == key]
        if group:
            ranks.append({**profile,'runs':len(group),'cost':sum(row['cost'] for row in group),
                          'iterations':sum(row['iterations'] for row in group),
                          'axe':average(row['axe'] for row in group if row['status'] in TERMINAL)})
    strategy = []
    for policy in policies:
        group = [row for row in chosen if row['policy'] == policy]
        if group:
            strategy.append(dict(id=policy,label=policy,color=STRATEGY_COLORS.get(policy, '#667085'),
                                 policy=policy,runs=len(group),iterations=sum(row['iterations'] for row in group),
                                 cost=sum(row['cost'] for row in group)))
    points = []
    for row in completed:
        if row['axe'] is None or row['original_axe'] is None:
            continue
        points.append({key:row[key] for key in ('id','profile','policy','axe','lighthouse','content','cost','seconds','iterations')}
                      | {'removed':row['original_axe']-row['axe']})
    trends = {key:[] for key in ('evaluations','evaluation_axe','evaluation_lighthouse',
                                  'runs','axe','lighthouse','seconds','cost')}
    for date in buckets:
        source_group = [row for row in evals if row['created_at'] is not None and bucket(row['created_at']) == date]
        run_group = [row for row in chosen if bucket(row['created']) == date]
        measured_group = [row for row in run_group if row['status'] in TERMINAL]
        trends['evaluations'].append(len(source_group))
        trends['runs'].append(len(run_group))
        for field in ('axe','lighthouse'):
            denominator = sum(row[field+'_n'] for row in source_group)
            value = (sum(float(row[field]) * row[field+'_n'] for row in source_group
                         if row[field] is not None) / denominator) if denominator else None
            trends['evaluation_'+field].append(value)
            trends[field].append(average(row[field] for row in measured_group))
        trends['seconds'].append(sum(row['seconds'] for row in run_group)+sum(float(row['seconds'] or 0) for row in source_group))
        trends['cost'].append(sum(row['cost'] for row in run_group)+sum(float(row['cost'] or 0) for row in source_group))
    return dict(totals=totals, profiles=list(profiles.values()), policies=policies,
                filters=dict(period=period,model=selected_model,policy=selected_policy,status=selected_status),
                timeline=timeline(ranks, 'profile'), strategy_timeline=timeline(strategy, 'policy'), trends=trends,
                models=sorted(ranks,key=lambda item:(-item['runs'],item['label'])),
                strategies=strategy, points=points, updated=now.isoformat(timespec='seconds'))


def activity(cursor, arguments, now, store=None, *, timezone_name='UTC'):
    evaluations, runs = read_rows(cursor)
    if store is None:
        from harness.store import Store
        store = Store()
    campaigns = CampaignReader(store, runs)
    for run in runs:
        # A dynamic run remains P5 even when its selected worker used P1 or P2.
        run['dynamic_level'] = dynamic_presentation(run, campaigns)
    return build_activity(evaluations, runs, arguments, now)
