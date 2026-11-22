"""Compare matched adaptive balances and correction/preservation profiles."""
import collections
import math
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .check_figure_resolution import check_figure
from .model_plot_style import (
    ADAPTIVE_STYLE, BALANCE_STYLES, STYLES, draw_pareto_frontier,
    outlined_scatter_style, place_point_labels, translucent_fill,
)

POLICIES = ('P0', 'P1', 'P2', 'P3', 'P4')


def criterion_vector(row):
    """Orient four criteria so greater values are always favorable."""
    result = (-row['axe'], row['lighthouse'], row['content_retention'], -row['cost_usd'])
    assert all(math.isfinite(value) for value in result)
    return result


def dominates(first, second):
    return (all(a >= b - 1e-9 for a, b in zip(first, second))
            and any(a > b + 1e-9 for a, b in zip(first, second)))


def paired_balances(fixed, adaptive):
    selected = {row['domain']: row for row in adaptive['rows'] if row['policy'] == 'P5'}
    assert len(selected) == fixed['domains'] == 30
    comparisons = []
    totals = {policy: collections.Counter() for policy in POLICIES}
    for row in fixed['rows']:
        peer = selected[row['domain']]
        assert peer['input_sha256'] == row['input_sha256']
        first, second = criterion_vector(peer), criterion_vector(row)
        status = ('adaptive' if dominates(first, second) else
                  'fixed' if dominates(second, first) else
                  'equal' if all(abs(a - b) <= 1e-9 for a, b in zip(first, second)) else
                  'tradeoff')
        totals[row['policy']][status] += 1
        comparisons.append({'domain': row['domain'], 'policy': row['policy'],
                            'profile': row['profile'], 'fixed_run_id': row['run_id'],
                            'p5_run_id': peer['run_id'], 'status': status})
    assert all(sum(values.values()) == 90 for values in totals.values())
    return comparisons, {policy: dict(values) for policy, values in totals.items()}


def endpoint_profiles(fixed, adaptive):
    points = []
    for policy in POLICIES:
        for profile in STYLES:
            rows = [r for r in fixed['rows'] if r['policy'] == policy and r['profile'] == profile]
            assert len(rows) == len({r['domain'] for r in rows}) == 30
            original = sum(r['original']['axe'] for r in rows)
            points.append({'policy': policy, 'profile': profile, 'domains': 30,
                           'source_axe': original,
                           'x': statistics.mean(r['content_retention'] for r in rows),
                           'axe': original - sum(r['axe'] for r in rows)})
    rows = [r for r in adaptive['rows'] if r['policy'] == 'P5']
    original = sum(r['axe'] for r in adaptive['originals'])
    points.append({'policy': 'P5', 'profile': 'adaptive', 'domains': 30,
                   'source_axe': original,
                   'x': statistics.mean(r['content_retention'] for r in rows),
                   'axe': original - sum(r['axe'] for r in rows)})
    assert len({point['source_axe'] for point in points}) == 1
    return points


def plot_balances(totals, output):
    fig, ax = plt.subplots(figsize=(7.2, 3.5))
    fig.subplots_adjust(left=.10, right=.98, bottom=.18, top=.82)
    previous = [0] * len(POLICIES)
    active = [key for key in BALANCE_STYLES if any(totals[p].get(key, 0) for p in POLICIES)]
    for key in active:
        label, color = BALANCE_STYLES[key]
        values = [totals[p].get(key, 0) for p in POLICIES]
        ax.barh(POLICIES, values, left=previous, height=.62,
                facecolor=translucent_fill(color), edgecolor=color, linewidth=1.25,
                zorder=3)
        for y, (left, count) in enumerate(zip(previous, values)):
            if count:
                ax.text(left + count / 2, y, str(count), ha='center', va='center', fontsize=9)
        previous = [left + count for left, count in zip(previous, values)]
    ax.set_xlim(0, 90)
    ax.invert_yaxis()
    ax.set_xticks(range(0, 91, 15))
    ax.set_xlabel('Matched source–configuration comparisons (90 per fixed policy)', fontsize=9)
    ax.set_ylabel('Fixed comparator', fontsize=9)
    ax.grid(axis='x', color='#DFE7EE', linewidth=.6, zorder=0)
    handles = [Patch(facecolor=translucent_fill(BALANCE_STYLES[key][1]),
                     edgecolor=BALANCE_STYLES[key][1], linewidth=1.25,
                     label=BALANCE_STYLES[key][0]) for key in active]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.54, .99),
               ncol=len(active), frameon=False, fontsize=8.5)
    path = output / 'model-strategy-cost.png'
    fig.savefig(path, dpi=1200, bbox_inches='tight', pad_inches=.04)
    plt.close(fig)
    check_figure(path)


def plot_preservation(points, output):
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    fig.subplots_adjust(left=.11, right=.98, bottom=.16, top=.77)
    for point in points:
        label, color, marker = (ADAPTIVE_STYLE if point['profile'] == 'adaptive'
                                else STYLES[point['profile']])
        ax.scatter(point['x'], point['axe'], s=30, marker=marker,
                   **outlined_scatter_style(color), zorder=4)
        text = (f"{point['policy']} · {point['axe']:.0f}"
                if point['policy'] in ('P2', 'P5') else point['policy'])
        offset = (-29, 10) if point['profile'] == 'luna-high' else (8, 9)
        if point['policy'] == 'P2' and point['profile'] == 'haiku-low':
            offset = (-29, -10)
        ax.annotate(text, (point['x'], point['axe']), xytext=offset,
                    textcoords='offset points', ha='center', va='center',
                    fontsize=8, color=color,
                    arrowprops={'arrowstyle': '-', 'color': '#91A1AE', 'lw': .45})
    frontier = draw_pareto_frontier(ax, points, prefer_high_x=True)
    ax.scatter([p[0] for p in frontier], [p[1] for p in frontier], s=115,
               facecolors='none', edgecolors='#53636F', linewidths=.8, zorder=3)
    ax.set_xlim(0, 108)
    expanded_correction_axis(ax)
    ax.set_xlabel('Mean content retention per source (%)', labelpad=8)
    ax.set_ylabel('Net Axe corrections across 30 sources')
    ax.grid(axis='y', color='#DFE7EE', linewidth=.6)
    handles = [Line2D([], [], linestyle='none', marker=marker, markersize=6,
                      markerfacecolor=translucent_fill(color), markeredgecolor=color,
                      markeredgewidth=1.25, label=label)
               for label, color, marker in [*STYLES.values(), ADAPTIVE_STYLE]]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.54, .995),
               ncol=2, frameon=False, fontsize=8.5)
    fig.legend(handles=[Line2D([], [], color='#53636F', linestyle=':', linewidth=.9,
                   marker='o', markerfacecolor='none', markeredgewidth=.8,
                   label='Nondominated observed profiles')], loc='upper center',
                   bbox_to_anchor=(.54, .855), frameon=False, fontsize=8)
    place_point_labels(fig)
    path = output / 'model-strategy-preservation.png'
    fig.savefig(path, dpi=1200, bbox_inches='tight', pad_inches=.04)
    plt.close(fig)
    check_figure(path)
    return frontier


def expanded_correction_axis(ax):
    """Enlarge 430–500 using a continuous, invertible piecewise-linear scale."""
    lower, upper, expansion, upper_slope = 430, 500, 8, 2
    transformed_upper = lower + expansion * (upper - lower)

    def forward(values):
        values = np.asarray(values, dtype=float)
        return (values + (expansion - 1) * np.maximum(values - lower, 0)
                + (upper_slope - expansion) * np.maximum(values - upper, 0))

    def inverse(values):
        values = np.asarray(values, dtype=float)
        return (values + (1 / expansion - 1) * np.maximum(values - lower, 0)
                + (1 / upper_slope - 1 / expansion)
                * np.maximum(values - transformed_upper, 0))

    ax.set_yscale('function', functions=(forward, inverse))
    ax.set_ylim(0, 550)
    ax.set_yticks([0, 150, 300, *range(lower, upper + 1, 10), 540])
    ax.text(.02, .98, 'Expanded Y scale: 430–500', transform=ax.transAxes,
            fontsize=7.5, va='top', color='#53636F')
    for boundary in (lower, upper):
        ax.axhline(boundary, color='#ABBAC8', linewidth=.65,
                   linestyle=(0, (4, 3)), zorder=1)
        position = ax.transAxes.inverted().transform(
            ax.transData.transform((0, boundary)))[1]
        ax.plot([0, 0], [position - .02, position + .02],
                transform=ax.transAxes, color='white', linewidth=3,
                clip_on=False, zorder=8)
        for shift in (-.008, .008):
            ax.plot([-.005, .005],
                    [position + shift - .006, position + shift + .006],
                    transform=ax.transAxes, color='#53636F', linewidth=.7,
                    clip_on=False, zorder=9)
