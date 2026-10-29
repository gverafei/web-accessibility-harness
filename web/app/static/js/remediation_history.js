/* Update only the visible list's active runs; leave filters and scroll intact. */
(function () {
  const table = document.querySelector('.remediation-history-table');
  if (!table) return;
  const input = document.getElementById('remediationListFilter');
  const count = document.getElementById('remediationFilterCount');
  const notice = document.getElementById('remediationLiveStatus');
  const rows = () => [...table.querySelectorAll('tbody tr[data-run-id]')];
  function filter() {
    if (table.closest?.('#remediationCatalogPanel')) return;
    if (table._historyPagination) { table._historyPagination.render(); return; }
    const term = input.value.trim().toLocaleLowerCase();
    const current = rows();
    let visible = 0;
    current.forEach(row => {
      row.hidden = Boolean(term && !row.textContent.toLocaleLowerCase().includes(term));
      const entry = row.closest?.('[data-history-entry]');
      if (entry) entry.hidden = row.hidden;
      if (!row.hidden) visible++;
    });
    count.textContent = `${visible} / ${current.length}`;
    table.dispatchEvent?.(new Event('history:filtered'));
  }
  input.addEventListener('input', filter);
  table.addEventListener('history:changed', filter);
  async function refresh() {
    const active = rows().filter(row => ['queued', 'running'].includes(row.dataset.runStatus));
    if (!active.length) {
      if (table.closest?.('#remediationCatalogPanel')) window.setTimeout(refresh, 4000);
      return;
    }
    try {
      if (!document.hidden && !window.warpInteractionActive?.()) {
        for (let start = 0; start < active.length; start += 50) {
          const batch = active.slice(start, start + 50);
          const url = new URL(window.location.href);
          url.search = '';
          url.searchParams.set('live_ids', batch.map(row => row.dataset.runId).join(','));
          const response = await fetch(url, {cache:'no-store'});
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const page = new DOMParser().parseFromString(`<table>${await response.text()}</table>`, 'text/html');
          const updated = [...page.querySelectorAll('tr[data-run-id]')];
          for (const row of batch) {
            const replacement = updated.find(item => item.dataset.runId === row.dataset.runId);
            if (replacement) {
              const entry = row.closest?.('[data-history-entry]');
              const next = replacement.closest?.('[data-history-entry]');
              if (entry && next) entry.replaceWith(next);
              else row.replaceWith(replacement);
            }
          }
        }
        notice.hidden = true;
        filter();
      }
    } catch {
      notice.hidden = false; // Retry without dropping the last measured state.
    }
    window.setTimeout(refresh, 4000);
  }
  filter();
  window.setTimeout(refresh, 4000);
})();
