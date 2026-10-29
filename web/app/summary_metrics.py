"""Measured page averages and observed strategy and fixed-worker rankings."""

import json
import math
from ipaddress import ip_address
from urllib.parse import urlsplit


def score_number(value):
    """Display integral audit scores without a decimal suffix."""
    return '—' if value is None else format(float(value), 'g')


def elapsed_time(seconds):
    seconds = round(float(seconds or 0))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours} h {minutes} min' if hours else f'{minutes} min {seconds} s'


def _local_url(url):
    host = (urlsplit(url).hostname or '').lower()
    if host in {'localhost', 'host.docker.internal'} or host.endswith('.localhost'):
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def evaluation_run_summary(rows):
    counts = dict(url=0, local=0, html=0, tranco=0, imported=0, combined=0)
    for row in rows:
        origin = row.get('experiment_origin')
        source = row.get('source_type')
        if origin in {'imported', 'composed'}:
            kind = 'imported' if origin == 'imported' else 'combined'
        elif source == 'tranco':
            kind = 'tranco'
        elif source == 'local_html':
            kind = 'html'
        else:
            urls = [url for url in (row.get('urls') or '').splitlines() if url.strip()]
            kind = 'local' if urls and all(_local_url(url) for url in urls) else 'url'
        counts[kind] += 1
    return dict(source_counts=counts,
                total_seconds=sum(float(row.get('execution_seconds') or 0) for row in rows))


def evaluation_metrics(cursor):
    cursor.execute("""SELECT AVG(axe_wcag_violations) average_axe,
        AVG(lighthouse_score) average_lighthouse
        FROM experiment_results WHERE status='completed'""")
    return cursor.fetchone() or {}


def remediation_metrics(cursor):
    cursor.execute("""SELECT AVG(ri.axe_wcag_violations) average_axe,
        AVG(ri.lighthouse_score) average_lighthouse
        FROM remediation_runs rr
        JOIN remediation_iterations ri ON ri.id=rr.accepted_iteration_id
        WHERE rr.status IN ('accepted','completed_with_warnings')""")
    return cursor.fetchone() or {}


def _measured_policy_population(rows, *, include_dynamic=False):
    """Keep P5 distinct; mixed-worker routes are not individual model results."""
    candidates, sources, models, levels = [], set(), set(), set()
    for row in rows:
        single_shot = row.get('execution_mode') == 'single_shot'
        dynamic = bool(row.get('dynamic_level'))
        level = 0 if single_shot else 5 if dynamic else row.get('presentation_level')
        if ((dynamic and not include_dynamic) or level not in (0, 1, 2, 3, 4, 5)
                or (not single_shot and not str(row.get('preservation_filter', '')).startswith('current-'))
                or row.get('original_axe') is None or row.get('result_axe') is None):
            continue
        model = row.get('generator_model') or row.get('actual_generator_model')
        source = row.get('source_result_id')
        if not model or model.startswith('system/') or source is None:
            continue
        effort = (row.get('model_presentation') or {}).get('reasoning_effort')
        models.add((model, effort))
        candidates.append(row)
        sources.add(source)
        levels.add(level)
    return candidates, {'sources': len(sources), 'levels': sorted(levels),
                        'models': len(models), 'runs': len(candidates)}


def observed_reducer_rankings(rows, *, strategies=False):
    measured, coverage = _measured_policy_population(rows, include_dynamic=strategies)
    groups = {}
    for row in measured:
        original, result = row['original_axe'], row['result_axe']
        if strategies:
            key = (0 if row.get('execution_mode') == 'single_shot'
                   else 5 if row.get('dynamic_level') else row['presentation_level'])
            label = 'P' + str(key)
        else:
            model = row.get('generator_model') or row['actual_generator_model']
            configuration = row.get('model_presentation') or {}
            effort = configuration.get('reasoning_effort')
            key = (model, effort)
            label = 'Luna' if model == 'openai/gpt-6-luna' else configuration.get('label') or model.split('/')[-1]
            if model.startswith('anthropic/') and label.lower().startswith('anthropic:'):
                label = label.split(':', 1)[1].strip()
            if effort:
                label += ' ' + ('light' if effort == 'low' else effort)
        group = groups.setdefault(key, {'label': label, 'original': 0, 'removed': 0,
                                        'paid_removed': 0, 'cost': 0, 'runs': 0,
                                        'content_sum': 0, 'content_runs': 0})
        removed = float(original) - float(result)
        group['original'] += float(original)
        group['removed'] += removed
        group['runs'] += 1
        try:
            strategy = json.loads(row.get('accepted_strategy_json') or '{}')
            retention = strategy.get('content_retention') or (strategy.get('source_fidelity') or {}).get('retention') or {}
            components = [retention.get(key) for key in ('text_percent', 'links_percent', 'images_percent')]
            if all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and 0 <= value <= 100 for value in components):
                group['content_sum'] += sum(components) / 3
                group['content_runs'] += 1
        except (ValueError, TypeError, AttributeError):
            pass
        recorded_cost = row.get('total_cost_usd')
        cost = float(recorded_cost) if recorded_cost is not None else None
        if cost is not None and cost >= 0 and not row.get('import_provenance_json'):
            group['cost'] += cost
            group['paid_removed'] += removed
    reductions, values, contents = [], [], []
    for group in groups.values():
        if not strategies or group['original'] > 0:
            score = 100 * group['removed'] / group['original'] if strategies else group['removed']
            reductions.append({**group, 'score': score})
        if group['content_runs'] == group['runs']:
            contents.append({**group, 'score': group['content_sum'] / group['content_runs']})
        if group['cost'] > 0:
            values.append({**group, 'score': group['paid_removed'] / group['cost']})
    order = lambda item: (-item['score'], item['label'])
    content_order = lambda item: (-item['score'],
                                  -item['removed'] / item['original'] if item['original'] else 0,
                                  item['cost'] / item['runs'], item['label'])
    return {'reduction': sorted(reductions, key=order), 'value': sorted(values, key=order),
            'content': sorted(contents, key=content_order), 'coverage': coverage}
