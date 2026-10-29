/* Keep list position and existing row listeners; summaries come from the server. */
(() => {
    let busy = false;
    window.warpDeleteListItem = async form => {
        if (busy) return;
        busy = true;
        const button = form.querySelector('button[type="submit"]');
        let done;
        try {
            if (!await window.warpConfirm(form.dataset.confirm, {
                danger: true, confirmLabel: form.dataset.confirmLabel,
            })) return;
            done = window.warpButtonBusy?.(button);
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            const response = await fetch(form.action, {
                method: 'POST', body: new FormData(form), cache: 'no-store',
            });
            if (!response.ok) throw new Error();
            const page = new DOMParser().parseFromString(await response.text(), 'text/html');
            const main = page.querySelector('main.app-main');
            if (!main) throw new Error();
            const messages = [...main.querySelectorAll('#appNotifications > .alert, :scope > .alert')];
            const stillPresent = [...main.querySelectorAll('form[data-list-delete]')]
                .some(item => item.getAttribute('action') === new URL(form.action).pathname);
            if (stillPresent || !messages.length) {
                await window.warpAlert(messages.map(item => item.textContent.trim()).join('\n') || form.dataset.deleteError);
                return;
            }
            const summary = main.querySelector('.summary-metrics');
            const currentSummary = document.querySelector('main .summary-metrics');
            if (summary && currentSummary) currentSummary.replaceWith(summary);
            const row = form.closest('tr');
            const table = row.closest('table');
            const scroll = table.closest('.table-responsive');
            const x = scroll.scrollLeft;
            const y = window.scrollY;
            (form.closest('[data-history-entry]') || row).remove();
            table.dispatchEvent(new CustomEvent('history:changed'));
            if (!table.querySelector('tbody tr')) {
                const emptyBody = main.querySelector('.card .card-body');
                if (emptyBody) table.closest('.card-body').replaceWith(emptyBody);
            }
            scroll.scrollLeft = x;
            window.scrollTo(window.scrollX, y);
            document.getElementById('listDeleteStatus')?.remove();
            const status = document.createElement('div');
            status.id = 'listDeleteStatus';
            status.className = 'alert alert-success shadow';
            status.setAttribute('role', 'status');
            Object.assign(status.style, {position: 'fixed', bottom: '1rem', right: '1rem', zIndex: '1050', maxWidth: 'min(32rem, 90vw)'});
            status.textContent = messages.map(item => item.textContent.trim()).join('\n');
            document.body.append(status);
            setTimeout(() => status.remove(), 6000);
            if (messages.some(item => !item.classList.contains('alert-success'))) {
                await window.warpAlert(status.textContent);
            }
        } catch (_) {
            // A lost response may follow a committed deletion: never retry automatically.
            await window.warpAlert(form.dataset.deleteError);
        } finally {
            done?.();
            button.disabled = false;
            button.removeAttribute('aria-busy');
            busy = false;
        }
    };
})();
