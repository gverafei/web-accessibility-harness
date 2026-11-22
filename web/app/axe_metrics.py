"""WCAG-only research metrics, separate from the preserved combined Axe count."""
import json
from pathlib import Path

POLICY = 'wcag-node-instances-v1'
FIELDS = ('violations', 'critical', 'serious', 'moderate', 'minor', 'failed_rules', 'needs_review')


def raw_metrics(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    violations = raw['violations']
    incomplete = raw.get('incomplete', [])
    if not isinstance(violations, list) or not isinstance(incomplete, list):
        raise ValueError('Invalid Axe evidence')
    def count(entries):
        return sum(len(entry['nodes']) for entry in entries)
    wcag = [entry for entry in violations if 'best-practice' not in entry.get('tags', [])]
    review = [entry for entry in incomplete if 'best-practice' not in entry.get('tags', [])]
    metrics = {'axe_wcag_violations': count(wcag),
               'axe_best_practice_issues': count(violations) - count(wcag),
               'axe_combined_violations': count(violations),
               'axe_wcag_failed_rules': len(wcag),
               'axe_wcag_needs_review': count(review),
               'axe_wcag_needs_review_rules': len(review), 'axe_counting_policy': POLICY}
    for impact in ('critical', 'serious', 'moderate', 'minor'):
        metrics['axe_wcag_' + impact] = count([entry for entry in wcag if entry.get('impact') == impact])
    return metrics


def candidate_metrics(summary):
    """Never substitute a combined count for a missing WCAG measurement."""
    if summary.get('raw_path') and Path(summary['raw_path']).is_file():
        metrics = raw_metrics(summary['raw_path'])
        if summary.get('wcag_violations') is not None and summary['wcag_violations'] != metrics['axe_wcag_violations']:
            raise RuntimeError('Axe WCAG summary disagrees with its raw evidence')
        return metrics
    if summary.get('wcag_violations') is None or summary.get('best_practice_issues') is None:
        raise RuntimeError('Incomplete Axe response: WCAG and Best Practices counts are required')
    for key in ('violations', 'wcag_violations', 'best_practice_issues'):
        value = summary.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError('Invalid Axe node count: ' + key)
    metrics = {'axe_wcag_' + key: summary.get('wcag_' + key) for key in FIELDS}
    metrics.update(axe_best_practice_issues=summary['best_practice_issues'],
                   axe_combined_violations=summary.get('violations'), axe_counting_policy=POLICY)
    if metrics['axe_combined_violations'] != metrics['axe_wcag_violations'] + metrics['axe_best_practice_issues']:
        raise RuntimeError('Inconsistent Axe separated counts')
    return metrics


def project_wcag(row):
    """Copy a stored row into the WCAG display/analysis domain; never mutate it.

    Already-normalized rows (SQL aliases or analysis inputs) need no projection.
    Explicit NULL separated counts remain unknown, never become combined or zero.
    """
    result = dict(row)
    extra = result.get('axe_metrics_json')
    if isinstance(extra, str):
        try: extra = json.loads(extra)
        except (ValueError, TypeError): extra = {}
    if isinstance(extra, dict): result.update(extra)
    if 'axe_wcag_violations' not in result: return result
    result.setdefault('axe_combined_violations', result.get('axe_violations'))
    for key in (*FIELDS, 'needs_review_rules'):
        field = 'axe_wcag_' + key
        if field in result: result['axe_' + key] = result[field]
    result['axe_counting_policy'] = POLICY
    return result


def persist_metrics(cursor, table, identifier, metrics, raw_path=None):
    if table not in {'remediation_iterations', 'comparison_members'}:
        raise ValueError('Unsupported Axe metrics table')
    fields = 'axe_wcag_violations=%s,axe_best_practice_issues=%s,axe_metrics_json=%s'
    values = [metrics['axe_wcag_violations'], metrics['axe_best_practice_issues'], json.dumps(metrics)]
    if table == 'remediation_iterations':
        fields += ',axe_raw_path=%s'; values.append(raw_path)
    cursor.execute(f'UPDATE {table} SET {fields} WHERE id=%s', (*values, identifier))
