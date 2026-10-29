"""Compare P1–P4 retention and total cost on matched frozen domain blocks."""
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from .check_figure_resolution import check_figure
from .model_plot_style import STYLES, outlined_scatter_style, place_point_labels, quadrant_legend, shade_preferred_quadrant



def matched_points(report):
    """Aggregate once per policy/configuration; reject incomplete or duplicate blocks."""
    points = []
    reference = None
    for profile in report['profiles']:
        for policy in ('P1', 'P2', 'P3', 'P4'):
            rows = [r for r in report['rows'] if r['profile'] == profile and r['policy'] == policy]
            sources = {(r['domain'], r['input_sha256']) for r in rows}
            assert len(rows) == len(sources) == report['domains']
            if reference is None:
                reference = sources
            assert sources == reference, 'All points must cover the same frozen sources'
            points.append({'profile': profile, 'policy': policy, 'n': len(rows),
                           'x': sum(r['cost_usd'] for r in rows),
                           'y': statistics.median(r['content_retention'] for r in rows),
                           'run_ids': sorted(r['run_id'] for r in rows)})
    return points


def plot(report, output):
    points = matched_points(report)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#ABBAC8', 'axes.labelcolor': '#253442',
        'text.color': '#253442', 'xtick.color': '#253442',
        'ytick.color': '#253442', 'axes.axisbelow': True})
    fig, ax = plt.subplots(figsize=(7, 3.55))
    fig.subplots_adjust(left=.10, right=.98, top=.76, bottom=.17)
    for profile in report['profiles']:
        label, color, _ = STYLES[profile]
        selected = [p for p in points if p['profile'] == profile]
        ax.scatter([p['x'] for p in selected], [p['y'] for p in selected],
                   s=40, **outlined_scatter_style(color),
                   label=label, zorder=4)
        for point in selected:
            ax.annotate(point['policy'], (point['x'], point['y']),
                        xytext=(0, -11) if point['y'] == 100 else (0, 11),
                        textcoords='offset points', ha='center', va='center',
                        fontsize=8, color=color,
                        bbox={'boxstyle': 'round,pad=.08', 'fc': 'white', 'ec': 'none', 'alpha': .9})
    ax.margins(x=.12)
    ax.set_xlim(left=0)
    ax.set_ylim(0, 108)
    ax.set_yticks(range(0, 101, 20))
    ax.set_xlabel(f'Total complete-run cost over {report["domains"]} domains (USD)', labelpad=7)
    ax.set_ylabel('Median content retention (%)', labelpad=7)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f'${x:g}'))
    ax.grid(axis='y', color='#DFE7EE', linewidth=.6)
    quadrant = shade_preferred_quadrant(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc='upper center',
               bbox_to_anchor=(.54, 1), ncol=3, frameon=False,
               fontsize=8.5, columnspacing=2.2, handletextpad=.4)
    quadrant_legend(fig, y=.905)
    place_point_labels(fig)
    name = 'strategy-retention-cost'
    fig.savefig(output / (name + '.png'), dpi=1200, bbox_inches='tight', pad_inches=.04)
    check_figure(output / (name + '.png'))
    plt.close(fig)
    return {'points': points, 'quadrant': quadrant}
