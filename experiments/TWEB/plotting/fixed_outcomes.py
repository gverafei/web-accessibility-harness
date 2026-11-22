"""Display retention and resource distributions for the fixed conditions."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from .model_plot_style import translucent_fill, STYLES, outlined_scatter_style
from .check_figure_resolution import check_figure


def plot(report, output):
    policies = ('P0', 'P1', 'P2', 'P3', 'P4')
    x = np.arange(len(policies))
    rows = report['rows']

    def group(policy, profile=None):
        return [row for row in rows if row['policy'] == policy
                and (profile is None or row['profile'] == profile)]

    def setup(axis, label, letter):
        axis.set_ylabel(label)
        axis.set_xticks(range(len(policies)), policies)
        axis.grid(axis='y', color='#DFE7EE', linewidth=.6)
        axis.text(0, 1.04, letter, transform=axis.transAxes,
                  fontsize=10, fontweight='bold')

    def save(figure, name):
        figure.canvas.draw()
        path = output / (name + '.png')
        figure.savefig(path, dpi=1200, bbox_inches='tight', pad_inches=.04)
        plt.close(figure)
        check_figure(path)

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#ABBAC8', 'axes.labelcolor': '#253442',
        'xtick.color': '#253442', 'ytick.color': '#253442', 'axes.axisbelow': True})
    fig, axes = plt.subplots(2, 2, figsize=(7, 6.1), layout='constrained')
    colors = ('#657785', '#215F97', '#087F89', '#7050A8', '#B87316')
    for ax, key, label, letter in zip(axes.flat, ('content_retention', 'cost_usd', 'seconds', 'iterations'),
                                    ('Content retained (%)', 'Included provider cost (US$)', 'Elapsed time (s)', 'Evaluated iterations'), ('A', 'B', 'C', 'D')):
        value = lambda r: len(r['iterations']) if key == 'iterations' else r[key]
        groups = [[value(r) for r in group(p) if value(r) is not None] for p in policies]
        boxes = ax.boxplot(groups, positions=x, patch_artist=True, showfliers=False, medianprops={'color':'#253442','linewidth':1.2})
        for box, color in zip(boxes['boxes'], colors):
            box.set_facecolor(translucent_fill(color)); box.set_alpha(None); box.set_edgecolor(color); box.set_linewidth(1.25)
        for index, p in enumerate(policies):
            for profile, dx, marker in (('luna-light', -.10, 'o'), ('luna-high', 0, 'o'), ('haiku-low', .10, 'o')):
                g = [r for r in group(p, profile) if value(r) is not None]; jitter = np.linspace(-.065, .065, len(g))
                ax.scatter(index+dx+jitter, [value(r) for r in g], s=10, marker=marker, **outlined_scatter_style(STYLES[profile][1]))
        setup(ax, label, letter)
        if key == 'content_retention': ax.set_ylim(-3, 110)
        if key == 'iterations': ax.set_yticks((0, 1, 3, 5, 7, 10))
    fig.legend(handles=[Line2D([], [], linestyle='', marker='o', color=color,
                        markerfacecolor=translucent_fill(color), markeredgewidth=1.25, label=label)
                        for label,color,_ in STYLES.values()], loc='outside upper center',ncol=3,frameon=False)
    save(fig, 'cut-fidelity-resources')
