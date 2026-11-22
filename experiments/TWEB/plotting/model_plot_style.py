"""Model identities using the paper's existing chart palette."""
STYLES = {
    'luna-light': ('Luna 6 light', '#215F97', 'o'),
    'luna-high': ('Luna 6 high', '#7050A8', 'o'),
    'haiku-low': ('Haiku 5.5 light', '#B87316', 'o'),
}


ADAPTIVE_STYLE = ('P5 adaptive', '#D54493', 'D')
POLICY_COLORS = {
    'P0': '#8896A6', 'P1': '#3B8BD9', 'P2': '#138B7B',
    'P3': '#9B6DDD', 'P4': '#E9A13B', 'P5': ADAPTIVE_STYLE[1],
}
BALANCE_STYLES = {
    'adaptive': ('P5 favorable', ADAPTIVE_STYLE[1]),
    'fixed': ('Fixed favorable', '#657785'),
    'tradeoff': ('Trade-off', STYLES['haiku-low'][1]),
    'equal': ('Equal', '#A7BDB2'),
}

STYLE_VERSION = 'figure8-model-identity-v1'
FILL_ALPHA = .20
OUTLINE_WIDTH = 1.25
# STYLES remains the three factorial profiles; do not widen a cohort by adding a family.
MODEL_STYLES = {
    **STYLES,
    'haiku-high': ('Haiku 5.5 high', STYLES['haiku-low'][1], 'o'),
    'sol-light': ('Sol 6.1 light', '#D4A900', 'o'),
    'sol-high': ('Sol 6.1 high', '#D4A900', 'o'),
    'astra-light': ('Astra 6 light', '#8996A8', 'o'),
    'astra-high': ('Astra 6 high', '#8996A8', 'o'),
    'opus-light': ('Opus 5.5 light', '#C73345', 'o'),
    'opus-high': ('Opus 5.5 high', '#C73345', 'o'),
    'sonnet-light': ('Sonnet 5.5 light', '#E2673D', 'o'),
    'sonnet-high': ('Sonnet 5.5 high', '#E2673D', 'o'),
}


def model_style(profile):
    """Require a registered identity instead of silently inventing a plot color."""
    return MODEL_STYLES[profile]


def outlined_scatter_style(color):
    """Reference Figure8 fill and stroke, independent of point size or data."""
    return {'facecolors': translucent_fill(color), 'edgecolors': color,
            'linewidths': OUTLINE_WIDTH}


def shade_preferred_quadrant(ax, *, prefer_high_x=False, prefer_high_y=True):
    """Bisect displayed ranges and shade the preferred trade-off direction."""
    from matplotlib.patches import Rectangle

    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    xmid = (xmin * xmax) ** .5 if ax.get_xscale() == 'log' else (xmin + xmax) / 2
    ymid = (ymin * ymax) ** .5 if ax.get_yscale() == 'log' else (ymin + ymax) / 2
    left = xmid if prefer_high_x else xmin
    width = xmax - xmid if prefer_high_x else xmid - xmin
    bottom = ymid if prefer_high_y else ymin
    height = ymax - ymid if prefer_high_y else ymid - ymin
    ax.add_patch(Rectangle((left, bottom), width, height,
                           facecolor='#E8F3EC', edgecolor='none', zorder=0))
    ax.axvline(xmid, color='#A7BDB2', linewidth=.6, zorder=1)
    ax.axhline(ymid, color='#A7BDB2', linewidth=.6, zorder=1)
    return {'x_boundary': xmid, 'y_boundary': ymid,
            'preferred': ('upper-' if prefer_high_y else 'lower-')
                         + ('right' if prefer_high_x else 'left')}


def place_point_labels(fig):
    """Keep point annotations close while avoiding other labels and markers."""
    from matplotlib.text import Annotation, Text
    from matplotlib.transforms import Bbox

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        annotations = [a for a in ax.texts if isinstance(a, Annotation)]
        unique = {}
        for annotation in annotations:
            key = (tuple(annotation.xy), annotation.get_text())
            if key in unique:
                unique[key].set_color('#253442')
                annotation.remove()
            else:
                unique[key] = annotation
        annotations = list(unique.values())
        for annotation in annotations:
            if annotation.arrow_patch is not None:
                annotation.arrow_patch.set_visible(False)
        points = [ax.transData.transform(a.xy) for a in annotations]
        placed = []
        area = ax.get_window_extent(renderer)
        bounds = Bbox.from_extents(area.x0 + 3, area.y0 + 3, area.x1 - 3, area.y1 - 3)
        candidates = [(0, 11), (0, -11), (11, 0), (-11, 0), (10, 11), (-10, 11),
                      (10, -11), (-10, -11), (0, 17), (0, -17), (17, 8), (-17, 8),
                      (17, -8), (-17, -8)]
        candidates += [(dx, dy) for dy in (21, -21, 17, -17, 0)
                       for dx in (0, 12, -12, 21, -21)]
        for annotation in annotations:
            initial = annotation.get_position()
            best = None
            for offset in [initial, *candidates]:
                annotation.set_position(offset)
                annotation.update_positions(renderer)
                box = Text.get_window_extent(annotation, renderer).expanded(1.12, 1.18)
                overlap = sum((min(box.x1, b.x1)-max(box.x0, b.x0)) *
                              (min(box.y1, b.y1)-max(box.y0, b.y0))
                              for b in placed if box.overlaps(b))
                marker_overlap = sum(box.overlaps(Bbox.from_extents(x-5, y-5, x+5, y+5)) for x, y in points)
                outside = not (bounds.contains(box.x0, box.y0) and bounds.contains(box.x1, box.y1))
                score = overlap*100 + marker_overlap*10000 + outside*1_000_000 + sum(v*v for v in offset)*.03
                if best is None or score < best[0]:
                    best = (score, offset, box)
            annotation.set_position(best[1]); placed.append(best[2])
        for annotation in annotations:
            if annotation.arrow_patch is not None:
                dx, dy = annotation.get_position()
                annotation.arrow_patch.set_visible(dx*dx + dy*dy > 16*16)


def draw_pareto_frontier(ax, points, *, prefer_high_x=False, prefer_high_y=True):
    """Connect only distinct nondominated observed coordinates, without smoothing."""
    coordinates = sorted(set((point['x'], point['axe']) for point in points))
    def dominates(first, second):
        x_better = first[0] >= second[0] if prefer_high_x else first[0] <= second[0]
        y_better = first[1] >= second[1] if prefer_high_y else first[1] <= second[1]
        return x_better and y_better and first != second
    frontier = [point for point in coordinates
                if not any(dominates(other, point) for other in coordinates)]
    if len(frontier) > 1:
        ax.plot([p[0] for p in frontier], [p[1] for p in frontier],
                color='#53636F', linewidth=.9, linestyle=':', zorder=2)
    return frontier


def quadrant_legend(fig, *, pareto=False, y=.91):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Patch(facecolor='#E8F3EC', edgecolor='#BCD6C5',
                     label='Most attractive quadrant')]
    if pareto:
        handles.append(Line2D([], [], color='#53636F', linewidth=.9,
                              linestyle=':', label='Pareto frontier'))
    return fig.legend(handles=handles, loc='upper center',
                      bbox_to_anchor=(.53,y), frameon=False, ncol=len(handles),
                      handlelength=1.7, handletextpad=.6, columnspacing=2)


def translucent_fill(color):
    """Share the reference figure's light fill with a separate opaque stroke."""
    from matplotlib.colors import to_rgba
    return to_rgba(color, FILL_ALPHA)


def outlined_bar_style(bars, colors):
    """Apply shared translucent fills without fading the solid series outlines."""
    for bar, color in zip(bars, colors):
        bar.set_alpha(None)
        bar.set_facecolor(translucent_fill(color))
        bar.set_edgecolor(color)
        bar.set_linewidth(OUTLINE_WIDTH)
