/* Read-only list updates, retaining controls, focus, maintenance and scroll. */
(function (root) {
    'use strict';
    function init(env = root) {
        const panel = env.document.getElementById('ragExamples');
        if (!panel) return;
        const form = panel.querySelector('form');
        const message = panel.querySelector('#ragBrowseMessage');
        let revision = 0, controller, debounce, disposed = false, pendingVersion = '', finishBusy;
        function invalidate() {
            ++revision;
            controller?.abort();
            finishBusy?.(); finishBusy = null;
            env.clearTimeout(debounce);
        }
        function formUrl() {
            const url = new URL(form.action, env.location.href);
            url.search = new URLSearchParams(new env.FormData(form)).toString();
            url.searchParams.set('page', '1');
            if (pendingVersion) url.searchParams.delete('collection');
            return url.href;
        }
        async function load(href, recovered = false, control = null) {
            const url = new URL(href, env.location.href);
            if (url.origin !== env.location.origin || url.pathname !== '/rag-act') return;
            invalidate();
            finishBusy = env.warpButtonBusy?.(control);
            const mine = revision;
            controller = new AbortController();
            const signal = controller.signal;
            const active = controller;
            const timeout = env.setTimeout(() => active.abort(), 10000);
            panel.setAttribute('aria-busy', 'true');
            message.textContent = panel.dataset.loading;
            try {
                const response = await env.fetch(url.href, {signal, headers:{Accept:'text/html'}});
                if (disposed || mine !== revision) return;
                if (response.status === 409 && !recovered) {
                    const latest = new URL(formUrl());
                    latest.searchParams.delete('collection');
                    return load(latest.href, true);
                }
                if (!response.ok) throw new Error(response.status === 409 ? panel.dataset.changedError : panel.dataset.loadError);
                const html = await response.text();
                if (disposed || mine !== revision) return;
                const next = new env.DOMParser().parseFromString(html, 'text/html').getElementById('ragExamples');
                const rows = next?.querySelector('tbody'), pager = next?.querySelector('.measurement-pagination');
                const summary = next?.querySelector('#ragExampleCounts');
                const provenance = next?.querySelector('#ragCorpusProvenance');
                const collection = next?.querySelector('[name="collection"]');
                if (!rows || !pager || !summary || !provenance || !collection) throw new Error(panel.dataset.loadError);
                const focusName = env.document.activeElement?.getAttribute('name');
                const focusPage = env.document.activeElement?.closest('.measurement-pagination a')?.getAttribute('aria-label');
                const toolbar = panel.querySelector('.report-pagination-toolbar');
                const top = toolbar.getBoundingClientRect().top;
                // Never execute returned scripts or insert the example HTML.
                panel.querySelector('tbody').innerHTML = rows.innerHTML;
                panel.querySelector('.measurement-pagination').innerHTML = pager.innerHTML;
                // Update counts only; preserve the static W3C catalogue link.
                panel.querySelector('#ragExampleCounts').textContent = summary.textContent;
                panel.querySelector('#ragCorpusProvenance').innerHTML = provenance.innerHTML;
                form.querySelector('[name="collection"]').value = collection.value;
                panel.dataset.corpusVersion = next.dataset.corpusVersion;
                pendingVersion = '';
                url.searchParams.set('collection', collection.value);
                if (focusName === 'size') panel.querySelector('[name="size"]').focus({preventScroll:true});
                else if (focusPage) {
                    const link = [...panel.querySelectorAll('.measurement-pagination a')]
                        .find(item => item.getAttribute('aria-label') === focusPage);
                    (link || panel.querySelector('[name="size"]')).focus({preventScroll:true});
                }
                env.history.replaceState(null, '', url.pathname + url.search);
                message.textContent = '';
                env.requestAnimationFrame(() => env.requestAnimationFrame(() => {
                    if (!disposed && mine === revision) {
                        const delta = toolbar.getBoundingClientRect().top - top;
                        if (Math.abs(delta) > .5) env.scrollBy({top:delta, behavior:'instant'});
                    }
                }));
            } catch (error) {
                if (!disposed && mine === revision) message.textContent = error.message === panel.dataset.changedError ? error.message : panel.dataset.loadError;
            } finally {
                env.clearTimeout(timeout);
                if (!disposed && mine === revision) {
                    finishBusy?.(); finishBusy = null;
                    pendingVersion = '';
                    panel.setAttribute('aria-busy', 'false');
                }
            }
        }
        panel.addEventListener('change', event => {
            if (event.target.matches('select')) load(formUrl());
        });
        panel.addEventListener('input', event => {
            if (event.target.name !== 'q') return;
            invalidate();
            panel.setAttribute('aria-busy', 'false');
            message.textContent = '';
            debounce = env.setTimeout(() => load(formUrl()), 250);
        });
        form.addEventListener('submit', event => { event.preventDefault(); load(formUrl(), false, event.submitter); });
        panel.addEventListener('click', event => {
            const link = event.target.closest('.measurement-pagination a');
            if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0) return;
            event.preventDefault();
            const url = new URL(formUrl());
            url.searchParams.set('page', new URL(link.href).searchParams.get('page') || '1');
            load(url.href, false, link);
        });
        function observeCorpus(event) {
            const version = event.detail?.version;
            if (!version || disposed || version === panel.dataset.corpusVersion || version === pendingVersion) return;
            pendingVersion = version;
            load(formUrl());
        }
        env.addEventListener('rag-corpus-observed', observeCorpus);
        return {load, dispose() {
            disposed = true; invalidate();
            env.removeEventListener('rag-corpus-observed', observeCorpus);
        }};
    }
    if (typeof module !== 'undefined') module.exports = {init};
    else {
        const control = init();
        root.addEventListener('pagehide', () => control?.dispose(), {once:true});
    }
})(typeof window !== 'undefined' ? window : globalThis);
