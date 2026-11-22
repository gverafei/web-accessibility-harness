"""Regenerate fixed-policy and iteration figures from this experiment's CSVs."""
import argparse
import collections
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from plotting.evidence import bind_inputs, read_csv, save_manifest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from plotting.check_figure_resolution import check_figure
from plotting.fixed_outcomes import plot as plot_distributions
from plotting.iteration_returns import measured_returns, plot as plot_iterations
from plotting.resource_shares import plot as plot_resources
from plotting.retention_cost import plot as plot_retention_cost
from plotting.taxonomy import failure_map

PROFILES = ('luna-light', 'luna-high', 'haiku-low')
FIGURES = {
    'cut-fidelity-resources': (5, 'fig:fidelity-resources'),
    'cut-taxonomy-failures': (6, 'fig:taxonomy-failures'),
    'strategy-retention-cost': (7, 'fig:strategy-retention-cost'),
    'model-resource-shares': (8, 'fig:resource-shares'),
    'model-strategy-iteration-returns': (12, 'fig:iteration-returns'),
}


def load_report():
    rows = read_csv(PACKAGE, 'runs.csv')
    sources = {row['domain']: row for row in read_csv(PACKAGE, 'sources.csv')}
    history = collections.defaultdict(list)
    for item in read_csv(PACKAGE, 'iterations.csv'):
        history[item['run_id']].append({
            'iteration_number': int(item['iteration']),
            'axe': int(item['axe']), 'lighthouse': float(item['lighthouse']),
            'retained': item['retained'].lower() in ('true', '1')})
    taxonomy = collections.defaultdict(lambda: collections.defaultdict(dict))
    for item in read_csv(PACKAGE, 'taxonomy.csv'):
        taxonomy[item['run_id']][item['side']][item['category']] = {
            'failed': int(item['failed']), 'coverage': float(item['coverage'])}
    numeric = ('axe', 'lighthouse', 'content_retention', 'cost_usd', 'seconds')
    for row in rows:
        source = sources[row['domain']]
        if row['input_sha256'] != source['input_sha256']:
            raise ValueError('Unmatched frozen input: ' + row['domain'])
        for field in numeric:
            row[field] = float(row[field])
        for field in ('input_tokens', 'output_tokens', 'total_tokens'):
            row[field] = int(row[field])
        row['original'] = {field: float(source[field]) for field in ('axe', 'lighthouse')}
        row['iteration_history'] = sorted(history[row['run_id']],
                                          key=lambda item: item['iteration_number'])
        row['iterations'] = [item['iteration_number'] for item in row['iteration_history']]
        if len(row['iterations']) != int(row['evaluated_versions']):
            raise ValueError('Evaluated version count differs: ' + row['run_id'])
        row['taxonomy'] = dict(taxonomy[row['run_id']])
    conditions = {(row['domain'], row['policy'], row['profile']) for row in rows}
    expected = {(domain, f'P{policy}', profile) for domain in sources
                for policy in range(5) for profile in PROFILES}
    if len(sources) != 30 or len(rows) != 450 or conditions != expected:
        raise ValueError('Expected thirty sources and 450 unique matched conditions')
    return {'domains': len(sources), 'profiles': PROFILES, 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=PACKAGE.parent / 'plots')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = bind_inputs(PACKAGE, ('sources.csv', 'runs.csv', 'iterations.csv', 'taxonomy.csv'))
    report = load_report()
    plot_distributions(report, output)
    figure = failure_map(report)
    target = output / 'cut-taxonomy-failures.png'
    figure.canvas.draw()
    figure.savefig(target, dpi=1200, bbox_inches='tight', pad_inches=.04)
    plt.close(figure)
    check_figure(target)
    retention = plot_retention_cost(report, output)
    resources = plot_resources(report, output)
    series = measured_returns(report)
    plot_iterations(series, output)
    totals = {policy: {
        'additional_versions': sum(item['additional_versions'][-1] for item in series
                                   if item['policy'] == policy),
        'additional_net_corrections': sum(item['additional_net_corrections'][-1]
                                          for item in series if item['policy'] == policy)}
        for policy in ('P1', 'P2', 'P3', 'P4')}
    medians = {policy: {
        field: statistics.median(row[field] for row in report['rows'] if row['policy'] == policy)
        for field in ('content_retention', 'cost_usd', 'seconds')}
        for policy in ('P0', 'P1', 'P2', 'P3', 'P4')}
    save_manifest(PACKAGE, output, inputs, FIGURES, {
        'conditions': len(report['rows']), 'retention_cost': retention,
        'resource_shares': resources, 'iteration_returns': series,
        'iteration_totals_by_policy': totals, 'distribution_medians': medians})


if __name__ == '__main__':
    main()
