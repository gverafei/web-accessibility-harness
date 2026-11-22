"""Compare one composite-retention endpoint per measured P4 configuration."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from matplotlib.legend_handler import HandlerTuple
from matplotlib.ticker import FixedLocator, FuncFormatter

from .check_figure_resolution import check_figure
from .model_plot_style import shade_preferred_quadrant, translucent_fill, place_point_labels, model_style, outlined_scatter_style



def plot(rows, output):
    assert 4 <= len(rows) <= 12 and len({r['profile'] for r in rows}) == len(rows)
    styles = {r['profile']: (model_style(r['profile'])[0].rsplit(' ', 1)[0], model_style(r['profile'])[1]) for r in rows}
    # Figure9 groups efforts by model; its Luna pair shares the registered blue.
    # Keep the global configuration palette unchanged for every other figure.
    for profile in styles:
        if profile.startswith('luna-'):
            styles[profile] = (styles[profile][0], model_style('luna-light')[1])
    for row in rows:
        components = [row[k] for k in ('text_percent', 'links_percent', 'images_percent')]
        assert all(0 <= v <= 100 for v in components)
        assert abs(sum(components)/3-row['content_retention']) < .011

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#ABBAC8',
        'axes.labelcolor': '#253442', 'text.color': '#253442', 'xtick.color': '#253442',
        'ytick.color': '#253442', 'axes.axisbelow': True})
    fig, ax = plt.subplots(figsize=(7, 4.1))
    fig.subplots_adjust(left=.085, right=.98, top=.75, bottom=.15)
    index = {r['profile']: r for r in rows}
    connections = []
    for family in (('luna-light', 'luna-medium', 'luna-high', 'luna-xhigh'),
                   ('haiku-low', 'haiku-high'), ('sol-light', 'sol-high'), ('astra-light', 'astra-high'), ('opus-light', 'opus-high'), ('sonnet-light', 'sonnet-high')):
        pair = [index[p] for p in family if p in index]
        if len(pair) >= 2:
            ax.plot([r['cost_usd'] for r in pair], [r['content_retention'] for r in pair],
                    color=styles[family[0]][1], linewidth=1.1, zorder=2)
            connections.append([r['profile'] for r in pair])
    points = []
    for row in rows:
        label, color = styles[row['profile']]
        ax.scatter(row['cost_usd'], row['content_retention'], marker='o', s=50,
                   **outlined_scatter_style(color), zorder=5)
        effort = row['profile'].rsplit('-', 1)[1]
        effort = 'light' if effort == 'low' else effort
        ax.annotate(effort, (row['cost_usd'], row['content_retention']), xytext=(8, 8),
                    textcoords='offset points', color=color, fontsize=7, ha='left', va='center')
        points.append({'profile': row['profile'], 'metric': 'content_retention',
                       'label': effort, 'model_label': label, 'color': color, 'marker': 'o',
                       'x': row['cost_usd'], 'y': row['content_retention']})
    ax.set_xscale('log')
    xmin = min(.07, min(r['cost_usd'] for r in rows)*.8)
    xmax = max(3.2, max(r['cost_usd'] for r in rows)*1.2)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(0, 100)
    ax.set_xlabel('Complete-run cost (USD, logarithmic scale)', labelpad=8)
    ax.set_ylabel('Content retention (%)')
    ax.xaxis.set_major_locator(FixedLocator([v for v in (.02, .05, .10, .20, .50, 1, 2, 5) if xmin <= v <= xmax]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, position: f'${value:g}'))
    ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.set_yticks(range(0, 101, 20))
    ax.grid(axis='y', color='#DFE7EE', linewidth=.6)
    quadrants = {'retention': shade_preferred_quadrant(ax)}
    # One model label and one color shared by its effort configurations.
    families = {}
    for profile, (label,color) in styles.items():
        families.setdefault(label, [])
        if color not in families[label]: families[label].append(color)
    handles = [tuple(Line2D([], [], marker='o', linestyle='none', markersize=6,
                      markerfacecolor=translucent_fill(color), markeredgecolor=color,
                      markeredgewidth=1.25) for color in colors) for colors in families.values()]
    fig.legend(handles, list(families), handler_map={tuple: HandlerTuple(ndivide=None, pad=.2)},
               loc='upper center', bbox_to_anchor=(.53, .995), ncol=3, frameon=False,
               fontsize=8.5, columnspacing=1.6)
    fig.legend(handles=[Patch(facecolor='#E8F3EC', edgecolor='#BCD6C5',
                             label='Most attractive quadrant')], loc='upper center',
               bbox_to_anchor=(.53, .88), frameon=False, fontsize=8.0)
    place_point_labels(fig)
    name = 'time-worker-family-tradeoff'
    output.mkdir(parents=True, exist_ok=True)
    output = output/f'{name}.png'
    fig.savefig(output, dpi=1200, bbox_inches='tight', pad_inches=.04)
    check_figure(output)
    plt.close(fig)
    return {'points': points, 'connections': connections, 'quadrants': quadrants,
            'model_legend': [{'label': label, 'colors': colors} for label, colors in families.items()]}
