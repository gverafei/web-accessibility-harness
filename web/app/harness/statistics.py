"""Agreement and paired page-clustered uncertainty, with explicit undefined values."""
import random
from collections import Counter, defaultdict


def _quantile(values, probability):
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def kappa(pairs):
    """None denotes missing annotation; unverified is an observed nominal label."""
    valid = [(a, b) for a, b in pairs if a is not None and b is not None]
    n = len(valid)
    if not n:
        return {'n': 0, 'coverage': 0., 'agreement': None, 'kappa': None, 'confusion': {}, 'marginals': {}}
    left, right = Counter(a for a, _ in valid), Counter(b for _, b in valid)
    po = sum(a == b for a, b in valid) / n
    pe = sum(left[label] * right[label] for label in left.keys() | right.keys()) / n ** 2
    matrix = defaultdict(dict)
    for (a, b), count in Counter(valid).items():
        matrix[a][b] = count
    return {'n': n, 'coverage': n / len(pairs), 'agreement': po,
            'kappa': (po - pe) / (1 - pe) if pe < 1 else None,
            'expected_agreement': pe, 'confusion': dict(matrix),
            'marginals': {'left': dict(left), 'right': dict(right)}}


def agreement_report(rows, iterations=1000, seed=0):
    # Rows contain page_id, left and right. Multiple repetitions stay in one cluster.
    report = kappa([(r.get('left'), r.get('right')) for r in rows])
    clusters = defaultdict(list)
    for row in rows:
        clusters[row['page_id']].append((row.get('left'), row.get('right')))
    keys = sorted(clusters)
    report.update(pages=len(keys), interval=None, bootstrap_valid=0,
                  uncertainty='95% percentile bootstrap clustered by page')
    if len(keys) < 2 or report['kappa'] is None:
        return report
    rng, samples = random.Random(seed), []
    for _ in range(iterations):
        pairs = [pair for _ in keys for pair in clusters[rng.choice(keys)]]
        value = kappa(pairs)['kappa']
        if value is not None:
            samples.append(value)
    report['bootstrap_valid'] = len(samples)
    if len(samples) >= iterations * .8:
        report['interval'] = [_quantile(samples, .025), _quantile(samples, .975)]
    return report


def paired_interval(rows, iterations=1000, seed=0):
    clusters = defaultdict(list)
    for page, difference in rows:
        clusters[page].append(difference)
    means = [sum(values) / len(values) for _, values in sorted(clusters.items())]
    if not means:
        return {'pages': 0, 'mean': None, 'interval': None}
    result = {'pages': len(means), 'mean': sum(means) / len(means), 'interval': None}
    if len(means) >= 2:
        rng = random.Random(seed)
        samples = [sum(rng.choice(means) for _ in means) / len(means) for _ in range(iterations)]
        result['interval'] = [_quantile(samples, .025), _quantile(samples, .975)]
    return result


def calibration(rows):
    verified = [r for r in rows if r.get('reference') in ('passed', 'violated') and r.get('prediction') in ('passed', 'violated')]
    harmful = [r for r in verified if r['reference'] == 'violated']
    accepted = [r for r in verified if r['prediction'] == 'passed']
    false_accept = sum(r['prediction'] == 'passed' for r in harmful)
    critical=[r for r in harmful if r.get('reference_critical') is True]
    critical_errors=sum(r['prediction']=='passed' for r in critical)
    return {'n': len(verified), 'reference_violations': len(harmful), 'predicted_passes': len(accepted),
            'false_acceptances': false_accept,
            'false_acceptance_rate': false_accept / len(harmful) if harmful else None,
            'false_pass_fraction': false_accept / len(accepted) if accepted else None,
            'coverage': len(verified) / len(rows) if rows else 0.,
            'critical_reference_violations':len(critical),'critical_false_acceptances':critical_errors,
            'critical_error_rate':critical_errors/len(critical) if critical else None,
            'severity_coverage':sum(r.get('reference_critical') is not None for r in harmful)/len(harmful) if harmful else None}
