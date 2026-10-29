"""Show the measured correction gained after each run's first evaluated output."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

from .check_figure_resolution import check_figure
from .model_plot_style import STYLES, outlined_scatter_style, translucent_fill

POLICIES = ('P1', 'P2', 'P3', 'P4')
TITLES = ('P1 · Minimal patches', 'P2 · Coordinated repair',
          'P3 · HTML regeneration', 'P4 · Markdown regeneration')


def retained_path(row):
    history = sorted(row['iteration_history'], key=lambda item: item['iteration_number'])
    assert 0 < len(history) == len(row['iterations']) <= 10
    path, selected = [], None
    for item in history:
        assert item['axe'] is not None
        if selected is None or item['retained']:
            selected = item['axe']
        path.append(selected)
    assert path[-1] == row['axe'], row['run_id']
    return path


def measured_returns(report):
    count, series = report['domains'], []
    for policy in POLICIES:
        for profile in STYLES:
            group = [r for r in report['rows']
                     if r['policy'] == policy and r['profile'] == profile]
            assert len(group) == len({r['domain'] for r in group}) == count
            paths = [retained_path(row) for row in group]
            rounds = list(range(1, max(map(len, paths)) + 1))
            extra_versions = [sum(min(step, len(path)) - 1 for path in paths)
                              for step in rounds]
            extra_corrections = [sum(path[0] - path[min(step, len(path)) - 1]
                                     for path in paths) for step in rounds]
            assert extra_corrections[-1] == sum(
                path[0] - row['axe'] for path, row in zip(paths, group))
            series.append({'policy': policy, 'profile': profile, 'domains': count,
                           'run_ids': [row['run_id'] for row in group],
                           'evaluated_round': rounds, 'additional_versions': extra_versions,
                           'additional_net_corrections': extra_corrections})
    return series


def plot(series, output):
    plt.rcdefaults()
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#ABBAC8', 'axes.labelcolor': '#253442',
        'text.color': '#253442', 'xtick.color': '#253442', 'ytick.color': '#253442'})
    fig, axes = plt.subplots(2, 2, figsize=(7.3, 5.0))
    fig.subplots_adjust(left=.10, right=.98, bottom=.15, top=.85,
                        wspace=.27, hspace=.40)
    for ax, policy, title in zip(axes.flat, POLICIES, TITLES):
        for item in (row for row in series if row['policy'] == policy):
            _, color, marker = STYLES[item['profile']]
            x, y = item['additional_versions'], item['additional_net_corrections']
            ax.plot(x, y, color=color, linewidth=1.2, zorder=3)
            ax.scatter(x, y, s=22, marker=marker,
                       **outlined_scatter_style(color), zorder=4)
        ax.set_title(title, fontsize=9.5, pad=9)
        ax.axhline(0, color='#A7B4BF', linewidth=.7, zorder=1)
        ax.grid(axis='y', color='#DFE7EE', linewidth=.6)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
        ax.margins(x=.06, y=.15)
    fig.supxlabel('Additional evaluated versions beyond the first output', fontsize=9, y=.025)
    fig.supylabel('Additional net Axe corrections', fontsize=9, x=.012)
    handles = [Line2D([], [], color=color, linewidth=1.2, marker=marker,
                     markerfacecolor=translucent_fill(color), markeredgecolor=color,
                     markeredgewidth=1.25, markersize=5, label=label)
               for label, color, marker in STYLES.values()]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.54, .99),
               ncol=3, frameon=False, fontsize=8.5)
    path = output / 'model-strategy-iteration-returns.png'
    fig.savefig(path, dpi=1200, bbox_inches='tight', pad_inches=.04)
    plt.close(fig)
    check_figure(path)
