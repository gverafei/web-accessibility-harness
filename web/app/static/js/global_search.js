/* Shared read-only search. Report links always go through the loading view. */
(function (root) {
    'use strict';
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
        char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
    function init(env) {
        const doc = env.document, overlay = doc.getElementById('searchOverlay');
        if (!overlay) return;
        const form = doc.getElementById('globalSearch'), trigger = doc.getElementById('globalSearchInput');
        const input = doc.getElementById('searchDialogInput'), results = doc.getElementById('searchSuggestions');
        let timer, controller, sequence = 0;
        const message = text => { results.innerHTML = `<p>${escapeHtml(text)}</p>`; };
        function cancel() {
            sequence++;
            env.clearTimeout(timer);
            controller?.abort();
            results.setAttribute('aria-busy', 'false');
        }
        function close() {
            cancel(); overlay.hidden = true; trigger.value = input.value;
        }
        function render(data) {
            if (!Array.isArray(data.experiments) || !Array.isArray(data.urls)) throw Error('Invalid search response');
            const link = (item, icon, title, detail) => {
                if (!/^\/experiments\/\d+\/loading(?:#url-results)?$/.test(item.href)) return '';
                return `<a class="search-result" href="${escapeHtml(item.href)}"><span class="search-result-icon">${escapeHtml(icon)}</span><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></span></a>`;
            };
            const html = [...data.experiments.map(item => link(item, `#${item.id}`, item.title, `${item.status} · ${item.date}`)),
                ...data.urls.map(item => link(item, 'URL', item.url, `#${item.experiment_id} · ${item.title}`))].join('');
            if (html) results.innerHTML = html; else message(overlay.dataset.empty);
        }
        async function search() {
            cancel();
            const current = sequence, query = input.value.trim();
            controller = new env.AbortController();
            const activeController = controller;
            const timeout = env.setTimeout(() => activeController.abort(), 10000);
            results.setAttribute('aria-busy', 'true');
            message(overlay.dataset.loading);
            try {
                const response = await env.fetch(`${overlay.dataset.url}?q=${encodeURIComponent(query)}`,
                    {signal: activeController.signal, headers: {Accept: 'application/json'}});
                if (!response.ok) throw Error('Search unavailable');
                const data = await response.json();
                if (current === sequence && !overlay.hidden) render(data);
            } catch (_) {
                if (current === sequence && !overlay.hidden) message(overlay.dataset.error);
            } finally {
                env.clearTimeout(timeout);
                if (current === sequence) results.setAttribute('aria-busy', 'false');
            }
        }
        function schedule() {
            cancel(); // Invalidate old results immediately, not after the debounce.
            message(overlay.dataset.loading);
            results.setAttribute('aria-busy', 'true');
            timer = env.setTimeout(search, 160);
        }
        function open() {
            overlay.hidden = false; input.value = trigger.value;
            input.focus(); input.select(); schedule();
        }
        trigger.addEventListener('focus', open);
        trigger.addEventListener('click', event => { event.preventDefault(); open(); });
        form.addEventListener('submit', event => {
            event.preventDefault(); env.location.assign(`${form.action}?q=${encodeURIComponent(input.value.trim())}`);
        });
        input.addEventListener('input', schedule);
        input.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault(); cancel();
                env.location.assign(`${form.action}?q=${encodeURIComponent(input.value.trim())}`);
            } else if (event.key === 'Escape') close();
        });
        overlay.querySelector('.search-backdrop').addEventListener('click', close);
        doc.addEventListener('keydown', event => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); open(); }
            else if (event.key === 'Escape' && !overlay.hidden) close();
        });
        return {open, close, search, schedule};
    }
    if (root.document) init(root);
    if (typeof module !== 'undefined') module.exports = {init, escapeHtml};
})(typeof window !== 'undefined' ? window : globalThis);
