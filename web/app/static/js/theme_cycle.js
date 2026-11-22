/* Shared icon-only theme control. Saving never navigates away from a form. */
(function (root) {
    'use strict';
    const order = ['dark', 'light', 'system'];
    const nextTheme = choice => order[(order.indexOf(choice) + 1) % order.length];
    function init(env) {
        const document = env.document, button = document.getElementById('themeCycle');
        if (!button) return;
        const html = document.documentElement;
        const status = document.getElementById('themeCycleStatus');
        const media = env.matchMedia('(prefers-color-scheme: dark)');
        const label = choice => button.dataset['label' + choice[0].toUpperCase() + choice.slice(1)];
        function render() {
            const choice = html.dataset.themeChoice;
            html.dataset.theme = choice === 'system' ? (media.matches ? 'dark' : 'light') : choice;
            const description = `${button.dataset.label}: ${label(choice)} → ${label(nextTheme(choice))}`;
            button.setAttribute('aria-label', description);
            button.title = description;
            button.querySelectorAll('[data-theme-icon]').forEach(icon => {
                icon.toggleAttribute('hidden', icon.dataset.themeIcon !== choice);
            });
            // Chart labels and axes must follow an in-place theme change too.
            if (env.Chart) {
                const color = html.dataset.theme === 'dark' ? '#cbd5e1' : '#334155';
                const grid = html.dataset.theme === 'dark' ? 'rgba(148,163,184,.22)' : 'rgba(51,65,85,.14)';
                env.Chart.defaults.color = color;
                env.Chart.defaults.borderColor = grid;
                Object.values(env.Chart.instances).forEach(chart => {
                    chart.options.color = color;
                    if (chart.options.plugins?.legend?.labels) chart.options.plugins.legend.labels.color = color;
                    for (const key of ['title', 'subtitle']) {
                        if (chart.options.plugins?.[key]) chart.options.plugins[key].color = color;
                    }
                    for (const scale of Object.values(chart.options.scales || {})) {
                        if (scale.ticks) scale.ticks.color = color;
                        if (scale.grid) scale.grid.color = grid;
                        if (scale.title) scale.title.color = color;
                        if (scale.border) scale.border.color = grid;
                    }
                    chart.update('none');
                });
            }
        }
        async function cycle() {
            if (button.disabled) return;
            const next = nextTheme(html.dataset.themeChoice);
            const done = env.warpButtonBusy?.(button);
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            status.textContent = '';
            try {
                const url = button.dataset['url' + next[0].toUpperCase() + next.slice(1)];
                const response = await env.fetch(url, {method: 'POST', credentials: 'same-origin',
                    headers: {Accept: 'application/json'}, signal: env.AbortSignal?.timeout(10000)});
                if (!response.ok || (await response.json()).theme !== next) throw new Error('Theme not saved');
                html.dataset.themeChoice = next;
                render();
                status.textContent = label(next);
            } catch (_) {
                status.textContent = button.dataset.error;
                button.title = button.dataset.error;
            } finally {
                done?.();
                button.disabled = false;
                button.removeAttribute('aria-busy');
                // A busy-state reset restores the old icon; render the saved choice.
                render();
            }
        }
        media.addEventListener('change', () => { if (html.dataset.themeChoice === 'system') render(); });
        button.addEventListener('click', cycle);
        render();
        return {cycle, render};
    }
    if (root.document) init(root);
    if (typeof module !== 'undefined') module.exports = {nextTheme, init};
})(typeof window !== 'undefined' ? window : globalThis);
