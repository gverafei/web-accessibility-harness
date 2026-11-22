"""Regenerate the four P5 comparison figures from this package's CSV evidence."""
import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))
from plotting.evidence import bind_inputs, save_manifest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from plotting.check_figure_resolution import check_figure
from plotting.model_plot_style import POLICY_COLORS, outlined_bar_style
from plotting.tradeoffs import paired_balances, endpoint_profiles, plot_balances, plot_preservation

POLICIES = tuple('P' + str(number) for number in range(6))
TAXONOMY = ('Syntactic', 'Semantic', 'Layout')
COMPONENTS = ('text_percent', 'links_percent', 'images_percent')
COLORS = tuple(POLICY_COLORS[policy] for policy in POLICIES)
FIGURES = {
    'p5-cost-quality': (10, 'fig:p5-cost-quality'),
    'p5-resource-bars': (11, 'fig:p5-resource-bars'),
    'model-strategy-cost': (13, 'fig:cost-quality'),
    'model-strategy-preservation': (14, 'fig:preservation-quality'),
}


def read_csv(name):
    with (PACKAGE / 'data' / name).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def load_comparison():
    sources = {row['domain']: row for row in read_csv('sources.csv')}
    rows = []
    numeric = ('axe', 'lighthouse', 'content_retention', 'cost_usd', 'seconds',
               'input_tokens', 'output_tokens', 'total_tokens', 'evaluated_candidates')
    for observed in read_csv('fixed-conditions.csv') + read_csv('runs.csv'):
        row = dict(observed)
        source = sources[row['domain']]
        if source['input_sha256'] != row['input_sha256']:
            raise ValueError('Unmatched frozen source: ' + row['domain'])
        row.update({key: float(row[key]) for key in numeric})
        row['failed'] = {key: float(row[key.lower() + '_failures']) for key in TAXONOMY}
        row['coverage'] = {key: float(row[key.lower() + '_coverage']) for key in TAXONOMY}
        row['retention'] = {key: float(row[key]) for key in COMPONENTS}
        row['original'] = {'axe': float(source['axe'])}
        row['billed_owned_cost_usd'] = row['cost_usd']
        rows.append(row)
    if len(sources) != 30 or len(rows) != 480:
        raise ValueError('Expected thirty matched sources and 480 selected outcomes')
    return {'domains': list(sources), 'rows': rows,
            'originals': [{'domain': name, 'axe': float(row['axe'])}
                          for name, row in sources.items()]}


def metric(row, name):
    if name.endswith('_coverage'):
        return row['coverage'][name.removesuffix('_coverage')]
    if name in TAXONOMY:
        return row['failed'][name]
    if name in COMPONENTS:
        return row['retention'][name]
    return row[name]


def per_source_values(comparison, policy, name):
    expected = 1 if policy == 'P5' else 3
    values = []
    for domain in comparison['domains']:
        matched = [row for row in comparison['rows']
                   if row['policy'] == policy and row['domain'] == domain]
        if len(matched) != expected:
            raise ValueError('Incomplete policy/source block: ' + policy + '/' + domain)
        values.append(statistics.mean(metric(row, name) for row in matched))
    return values


def summarize(comparison):
    names = ('axe', 'lighthouse', *TAXONOMY, *(name + '_coverage' for name in TAXONOMY),
             *COMPONENTS, 'content_retention',
             'cost_usd', 'seconds', 'input_tokens', 'output_tokens', 'total_tokens',
             'evaluated_candidates')
    result = []
    for policy in POLICIES:
        selected = [row for row in comparison['rows'] if row['policy'] == policy]
        result.append({'policy': policy, 'conditions': len(selected),
                       **{name: statistics.mean(per_source_values(comparison, policy, name))
                          for name in names},
                       'observed_cost_usd': sum(row['cost_usd'] for row in selected)})
    return result


def grouped_bars(comparison, output):
    quality = [('axe', 'Axe findings ↓', 1), ('lighthouse', 'Lighthouse score ↑', 1),
               ('Syntactic', 'Syntactic failures ↓', 1), ('Semantic', 'Semantic failures ↓', 1),
               ('Layout', 'Layout failures ↓', 1), ('content_retention', 'Content retention (%) ↑', 1)]
    resources = [('cost_usd', 'Complete cost (USD) ↓', 1),
                 ('seconds', 'Complete time (min) ↓', 1 / 60),
                 ('total_tokens', 'Total tokens (K) ↓', 1 / 1000),
                 ('evaluated_candidates', 'Evaluated candidates ↓', 1)]
    for filename, panels, shape, size in (
            ('p5-cost-quality', quality, (2, 3), (7.5, 4.7)),
            ('p5-resource-bars', resources, (2, 2), (7.5, 4.5))):
        figure, axes = plt.subplots(*shape, figsize=size)
        figure.subplots_adjust(left=.075, right=.99, bottom=.09, top=.91,
                               wspace=.30, hspace=.65)
        for axis, (name, title, scale) in zip(axes.flat, panels):
            groups = [np.asarray(per_source_values(comparison, policy, name)) * scale
                      for policy in POLICIES]
            means = [float(values.mean()) for values in groups]
            bars = axis.bar(POLICIES, means, width=.65, zorder=3)
            outlined_bar_style(bars, COLORS)
            bounds = []
            for values in groups:
                generator = np.random.default_rng(20261013)
                draws = generator.choice(values, size=(10000, len(values)), replace=True).mean(axis=1)
                bounds.append(np.quantile(draws, [.025, .975]))
            for position, (value, bound) in enumerate(zip(means, bounds)):
                lower, upper = min(value, bound[0]), max(value, bound[1])
                axis.plot([position, position], [lower, upper], color='#425261', lw=.8, zorder=4)
                axis.plot([position - .06, position + .06], [lower, lower], color='#425261', lw=.8, zorder=4)
                axis.plot([position - .06, position + .06], [upper, upper], color='#425261', lw=.8, zorder=4)
                label = f'{value:.3f}' if name == 'cost_usd' else f'{value:.1f}'
                axis.annotate(label, (position, upper), xytext=(0, 4), textcoords='offset points',
                              ha='center', fontsize=7)
            axis.set_title(title, fontsize=9, pad=14)
            axis.grid(axis='y', color='#E3EAF0', lw=.6, zorder=0)
            axis.tick_params(axis='x', length=0, labelsize=8)
            maximum = max(bound[1] for bound in bounds)
            if name in ('lighthouse', 'content_retention'):
                axis.set_ylim(0, 110)
                axis.set_yticks([0, 25, 50, 75, 100])
            else:
                axis.set_ylim(0, maximum * 1.23 if maximum > 0 else 1)
        target = output / (filename + '.png')
        figure.savefig(target, dpi=1200, bbox_inches='tight', pad_inches=.035)
        check_figure(target)
        plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=PACKAGE.parent / 'plots')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = bind_inputs(PACKAGE, ('sources.csv', 'runs.csv', 'fixed-conditions.csv'))
    comparison = load_comparison()
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#ABBAC8', 'axes.labelcolor': '#253442',
        'text.color': '#253442', 'xtick.color': '#253442', 'ytick.color': '#253442'})
    grouped_bars(comparison, output)
    fixed = {'domains': 30, 'rows': [row for row in comparison['rows'] if row['policy'] != 'P5']}
    adaptive = {'domains': 30, 'rows': [row for row in comparison['rows'] if row['policy'] == 'P5'],
                'originals': comparison['originals']}
    pairs, totals = paired_balances(fixed, adaptive)
    points = endpoint_profiles(fixed, adaptive)
    plot_balances(totals, output)
    frontier = plot_preservation(points, output)
    metadata = output / 'metadata'
    metadata.mkdir(exist_ok=True)
    report = {'means': summarize(comparison), 'paired_comparisons': pairs,
              'paired_totals': totals, 'profile_points': points, 'frontier': frontier,
              'source_files': {name: hashlib.sha256((PACKAGE / 'data' / name).read_bytes()).hexdigest()
                               for name in ('sources.csv', 'runs.csv', 'fixed-conditions.csv')},
              'aggregation': 'Equal-source means; fixed configurations averaged within each source.',
              'intervals': '95% percentile intervals from 10000 whole-source resamples.',
              'provider_calls': 0}
    (metadata / 'p5-comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    save_manifest(PACKAGE, output, inputs, FIGURES, report)


if __name__ == '__main__':
    main()
