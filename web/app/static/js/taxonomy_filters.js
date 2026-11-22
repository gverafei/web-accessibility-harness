/* GET-only catalog browsing: keep controls, focus and viewport in place. */
(function (root) {
    'use strict';
    function init(env = root) {
        const panel = env.document.getElementById('taxonomyCatalogPanel') ||
            env.document.getElementById('memoryCatalogPanel') ||
            env.document.getElementById('remediationCatalogPanel');
        if (!panel) return;
        const form = panel.querySelector('form');
        const message = panel.querySelector('#taxonomyBrowseMessage');
        const rowSelector = panel.dataset.catalogRows ||
            (panel.id === 'remediationCatalogPanel' ? 'table' : 'tbody');
        const rows = panel.querySelector(rowSelector);
        const pager = panel.querySelector('.measurement-pagination');
        const results = panel.querySelector('.taxonomy-results') || panel.querySelector('.catalog-results');
        let revision = 0;
        let controller;
        let debounce;
        let disposed = false;

        function formUrl() {
            const url = new URL(form.action, env.location.href);
            url.search = new URLSearchParams(new env.FormData(form)).toString();
            url.searchParams.set('page', '1');
            return url.href;
        }

        async function load(href, paging = false) {
            const url = new URL(href, env.location.href);
            const endpoint = new URL(form.action, env.location.href);
            if (url.origin !== env.location.origin || url.pathname !== endpoint.pathname) return;
            controller?.abort();
            const mine = ++revision;
            controller = new AbortController();
            const active = controller;
            const timeout = env.setTimeout(() => active.abort(), 10000);
            panel.setAttribute('aria-busy', 'true');
            message.textContent = '';
            try {
                const response = await env.fetch(url.href, {
                    signal: active.signal, headers: {Accept: 'text/html'}
                });
                if (!response.ok) throw Error('Catalog request failed');
                const html = await response.text();
                if (disposed || mine !== revision) return;
                const nextDocument = new env.DOMParser().parseFromString(html, 'text/html');
                const next = nextDocument.getElementById(panel.id);
                const freshRows = next?.querySelector(rowSelector);
                const freshPager = next?.querySelector('.measurement-pagination');
                if (!freshRows || !freshPager) throw Error('Missing catalog');
                const focusedPage = env.document.activeElement
                    ?.closest('.measurement-pagination a')?.getAttribute('aria-label');
                const top = form.getBoundingClientRect().top;
                // Preserve document height when navigating to a short last page.
                results.style.minHeight = paging ? results.getBoundingClientRect().height + 'px' : '';
                const summary = env.document.getElementById('reviewSummary');
                const freshSummary = summary && nextDocument.getElementById('reviewSummary');
                if (freshSummary) summary.innerHTML = freshSummary.innerHTML;
                rows.innerHTML = freshRows.innerHTML;
                if (rowSelector === 'table') rows.dispatchEvent(new Event('history:changed'));
                pager.innerHTML = freshPager.innerHTML;
                if (focusedPage) {
                    const link = [...pager.querySelectorAll('a')]
                        .find(item => item.getAttribute('aria-label') === focusedPage);
                    (link || form.querySelector('[name="size"]')).focus({preventScroll: true});
                }
                env.history.replaceState(null, '', url.pathname + url.search);
                env.requestAnimationFrame(() => env.requestAnimationFrame(() => {
                    if (disposed || mine !== revision) return;
                    const delta = form.getBoundingClientRect().top - top;
                    if (Math.abs(delta) > .5) env.scrollBy({top: delta, behavior: 'instant'});
                }));
            } catch (error) {
                if (!disposed && mine === revision) message.textContent = panel.dataset.loadError;
            } finally {
                env.clearTimeout(timeout);
                if (!disposed && mine === revision) panel.setAttribute('aria-busy', 'false');
            }
        }

        panel.addEventListener('input', event => {
            if (event.target.name !== 'q') return;
            ++revision;
            controller?.abort();
            env.clearTimeout(debounce);
            panel.setAttribute('aria-busy', 'false');
            message.textContent = '';
            debounce = env.setTimeout(() => load(formUrl()), 250);
        });
        form.addEventListener('submit', event => {
            event.preventDefault();
            env.clearTimeout(debounce);
            load(formUrl());
        });
        panel.addEventListener('change', event => {
            if (panel.id === 'remediationCatalogPanel' && !form.contains(event.target)) return;
            if (event.target.name === 'q') return;
            env.clearTimeout(debounce);
            load(formUrl());
        });
        panel.addEventListener('click', event => {
            const link = event.target.closest('.measurement-pagination a');
            if (!link || event.ctrlKey || event.metaKey || event.shiftKey ||
                event.altKey || event.button > 0) return;
            event.preventDefault();
            load(link.href, true);
        });
        const refreshMs = Number(panel.dataset.refreshMs);
        let refresh;
        const refreshList = async () => {
            if (disposed) return;
            if (!form.contains(env.document.activeElement)) await load(env.location.href, true);
            if (!disposed) refresh = env.setTimeout(refreshList, refreshMs);
        };
        if (refreshMs >= 5000) refresh = env.setTimeout(refreshList, refreshMs);
        return {
            load,
            dispose() {
                disposed = true;
                ++revision;
                env.clearTimeout(debounce);
                env.clearTimeout(refresh);
                controller?.abort();
            }
        };
    }
    if (typeof module === 'object' && module.exports) {
        module.exports = {init};
    } else {
        const control = init();
        root.addEventListener('pagehide', () => control?.dispose(), {once: true});
    }
})(typeof window === 'undefined' ? globalThis : window);
