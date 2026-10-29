"""Render source and selected-output taxonomic failures by domain."""
import statistics


def failure_map(report):
    """One source column and five outcome columns, retaining between-page variation."""
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib import colors, patches

    domains = sorted({r['domain'] for r in report['rows']}, key=str.casefold)
    policies = ('Source', 'P0', 'P1', 'P2', 'P3', 'P4')
    dimensions = ('Syntactic', 'Semantic', 'Layout')
    panels = []
    maximum = 1
    for dimension in dimensions:
        matrix = []
        for domain in domains:
            counts = []
            for policy in policies:
                group = [r for r in report['rows'] if r['domain'] == domain
                         and r['policy'] == ('P1' if policy == 'Source' else policy)]
                side = 'original' if policy == 'Source' else 'retained'
                metrics = []
                for row in group:
                    taxonomy = row['taxonomy'][side]
                    if taxonomy and dimension in taxonomy.get('categories', taxonomy):
                        metrics.append(taxonomy.get('categories', taxonomy)[dimension])
                counts.append(statistics.median(m['failed'] for m in metrics) if metrics else None)
            matrix.append(counts)
        maximum = max(maximum, max((v for row in matrix for v in row if v is not None), default=0))
        panels.append(matrix)
    palette = colors.LinearSegmentedColormap.from_list(
        'paper_failures', ['#FFFFFF', '#D5E6F1', '#7AABCD', '#215F97', '#423366'])
    norm = colors.FuncNorm((np.log1p, np.expm1), vmin=0, vmax=maximum)
    fig, axes = plt.subplots(1, 3, figsize=(7, max(5.4, len(domains) * .17 + 1.25)))
    fig.subplots_adjust(left=.19, right=.98, bottom=.14, top=.94, wspace=.18)
    for index, (ax, dimension, matrix) in enumerate(zip(axes, dimensions, panels)):
        for y, row in enumerate(matrix):
            for x, count in enumerate(row):
                ax.add_patch(patches.Rectangle((x - .49, y - .49), .98, .98,
                    facecolor=palette(norm(count)) if count is not None else '#F0F2F4', edgecolor='#D7E0E7', linewidth=.3))
                if count:
                    ax.text(x, y, f'{count:g}', ha='center', va='center', fontsize=6.8,
                            color='white' if norm(count) > .6 else '#253442')
        ax.set(xlim=(-.5, 5.5), ylim=(len(domains) - .5, -.5))
        ax.set_xticks(range(6), ('Src', 'P0', 'P1', 'P2', 'P3', 'P4'), fontsize=7.5)
        ax.set_yticks(range(len(domains)), domains if index == 0 else [], fontsize=7.5)
        ax.tick_params(length=0, pad=4)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.set_title(dimension, fontsize=9, pad=11)
    color_axis = fig.add_axes((.31, .055, .55, .018))
    for index in range(128):
        color_axis.add_patch(patches.Rectangle((index / 128, 0), 1 / 128, 1,
                                              facecolor=palette(index / 127), edgecolor='none'))
    ticks = [v for v in (0, 1, 5, 20, 100, 500, 2000) if v <= maximum]
    color_axis.set(xlim=(0, 1), ylim=(0, 1), yticks=[])
    color_axis.set_xticks([float(norm(v)) for v in ticks], [f'{v:g}' for v in ticks])
    color_axis.tick_params(labelsize=7, length=2)
    color_axis.set_xlabel('Observed failed opportunities (logarithmic color scale)', fontsize=8, labelpad=4)
    return fig
