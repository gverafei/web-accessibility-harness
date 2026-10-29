"""Plot the three observed repetitions at their exact selected endpoints."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from .model_plot_style import translucent_fill
from .check_figure_resolution import check_figure


def plot(rows, output):
    domains = list(dict.fromkeys(r['domain'] for r in rows))
    keys = [(d, p) for d in domains for p in ('P1', 'P2')]
    lookup = {(r['domain'], r['policy'], r['repeat']): r for r in rows}
    metrics = [('Axe findings', lambda r: r['axe']),
               ('Lighthouse', lambda r: r['lighthouse']),
               ('Syntactic failures', lambda r: r['failed']['Syntactic']),
               ('Semantic failures', lambda r: r['failed']['Semantic']),
               ('Layout failures', lambda r: r['failed']['Layout'])]
    colors = ['#2776B8', '#D57922', '#8653B2']
    markers = ['o', 's', 'D']
    sizes = [8, 5.6, 2.8]
    styles = ['-', '--', ':']
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                         'axes.labelcolor': '#253442', 'text.color': '#253442'})
    fig, axes = plt.subplots(5, 1, figsize=(7.0, 5.8), sharex=True)
    fig.subplots_adjust(left=.205, right=.965, top=.91, bottom=.10, hspace=.22)
    for ax, (name, get) in zip(axes, metrics):
        for i in range(5):
            if i % 2 == 0:
                ax.axvspan(2*i-.45, 2*i+1.45, color='#EDF3F8', zorder=0)
        for n in (1, 2, 3):
            vals = [get(lookup[d, p, n]) for d, p in keys]
            ax.plot(range(10), vals, color=colors[n-1], linestyle=styles[n-1],
                    linewidth=1.15, marker=markers[n-1], markersize=sizes[n-1],
                    markerfacecolor=translucent_fill(colors[n-1]),
                    markeredgewidth=1.25, label=f'Repetition {n}', zorder=n+2)
        all_values = [get(r) for r in rows]
        delta = max(max(get(lookup[d,p,n]) for n in (1,2,3)) - min(get(lookup[d,p,n]) for n in (1,2,3)) for d,p in keys)
        ax.text(-.245, .5, name, transform=ax.transAxes, va='center', ha='left', fontsize=9)
        ax.text(1.01, .5, f'{delta:g}', transform=ax.transAxes, va='center', fontsize=9, fontweight='bold')
        low, high = min(all_values), max(all_values)
        pad = max((high-low)*.16, .25)
        ax.set_ylim(low-pad, high+pad)
        ax.set_yticks(sorted(set([low, high])))
        ax.grid(axis='y', color='#DDE4EA', linewidth=.6)
        ax.spines[['top', 'right', 'bottom']].set_visible(False)
        ax.spines['left'].set_color('#C4CDD5')
        ax.tick_params(axis='x', length=0)
        ax.set_xlim(-.45, 9.45)
    axes[0].text(1.01, 1.18, 'Max.\nrange', transform=axes[0].transAxes, ha='center', fontsize=8)
    labels = [p for d,p in keys]
    axes[-1].set_xticks(range(10), labels)
    for i,d in enumerate(domains):
        axes[-1].text(2*i+.5, -.55, {'blackberry.com': 'BlackBerry', 'hbr.org': 'HBR'}.get(d, d.split('.')[0].capitalize()), transform=axes[-1].get_xaxis_transform(), ha='center', fontsize=9)
    handles = [Line2D([],[],color=colors[n-1],linestyle=styles[n-1],marker=markers[n-1],markersize=sizes[n-1], markerfacecolor='white' if n<3 else colors[n-1],label=f'Repetition {n}') for n in (1,2,3)]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.57,.995),ncol=3,frameon=False, handlelength=2.8,columnspacing=2)
    fig.canvas.draw()
    assert len(rows)==30 and len(lookup)==30
    out = output / 'repeatability-alignment.png'
    fig.savefig(out, dpi=1200, facecolor='white')
    plt.close(fig)
    check_figure(out)
