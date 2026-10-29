"""Normalize complete execution resources across the three repair configurations."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from .check_figure_resolution import check_figure
from .model_plot_style import STYLES, outlined_bar_style


def plot(report, output):
    rows = report['rows']
    profiles = ('luna-light', 'luna-high', 'haiku-low')
    values = {profile: [
        sum(row['cost_usd'] for row in rows if row['profile'] == profile),
        sum(row['seconds'] for row in rows if row['profile'] == profile) / 3600,
        sum(len(row['iterations']) for row in rows if row['profile'] == profile),
        sum(row['input_tokens'] for row in rows if row['profile'] == profile),
        sum(row['output_tokens'] for row in rows if row['profile'] == profile),
        sum(row['total_tokens'] for row in rows if row['profile'] == profile)]
        for profile in profiles}
    totals = [sum(values[p][i] for p in profiles) for i in range(6)]
    formatters = (lambda v: f'${v:.2f}', lambda v: f'{v:.2f} h', lambda v: f'{v:,.0f}',
                  lambda v: f'{v/1e6:.2f} M', lambda v: f'{v/1e6:.2f} M', lambda v: f'{v/1e6:.2f} M')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#ABBAC8',
        'axes.labelcolor': '#253442', 'text.color': '#253442', 'xtick.color': '#253442',
        'ytick.color': '#253442', 'axes.axisbelow': True})
    fig, ax = plt.subplots(figsize=(7, 3.7))
    fig.subplots_adjust(left=.10, right=.98, top=.80, bottom=.15)
    bottom = [0.0] * 6
    for profile in profiles:
        label, color, _ = STYLES[profile]
        shares = [100 * value / total for value, total in zip(values[profile], totals)]
        bars = ax.bar(range(6), shares, .69, bottom=bottom, color=color, label=label, zorder=3)
        outlined_bar_style(bars, [color] * len(bars))
        for i, (share, value) in enumerate(zip(shares, values[profile])):
            ax.text(i, bottom[i] + share / 2, f'{formatters[i](value)}\n{share:.1f}%',
                    ha='center', va='center', color='#253442', fontsize=8)
            bottom[i] += share
    for i, total in enumerate(totals):
        ax.text(i, 104, formatters[i](total), ha='center', va='bottom', fontsize=9, fontweight='normal')
    ax.set_xticks(range(6), ('Cost', 'Time', 'Evaluated\niterations', 'Input\ntokens', 'Output\ntokens', 'Total\ntokens'))
    ax.set_ylabel('Share of each resource total (%)')
    ax.set_ylim(0, 115); ax.set_yticks((0, 25, 50, 75, 100))
    ax.yaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.grid(axis='y', color='#DFE7EE', linewidth=.6)
    fig.legend(*ax.get_legend_handles_labels(), loc='upper center', bbox_to_anchor=(.54, .995),
               ncol=3, frameon=False)
    name = 'model-resource-shares'
    path = output / (name + '.png')
    fig.savefig(path, dpi=1200, bbox_inches='tight', pad_inches=.04); check_figure(path)
    plt.close(fig)
    return {'values': values, 'totals': dict(zip(
        ('cost_usd', 'hours', 'iterations', 'input_tokens', 'output_tokens', 'total_tokens'), totals))}
