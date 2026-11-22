/* Selection stays on the same records in table/cards, filtering and live updates. */
(function (root) {
  function init(env = root) {
    env.document.querySelectorAll('form[data-history-selection]').forEach(form => {
      const table = env.document.querySelector(form.dataset.historySelection);
      if (!table) return;
      const all = form.querySelector('[data-history-select-all]');
      const button = form.querySelector('[data-history-export]');
      const count = form.querySelector('[data-history-selection-count]');
      const serverPaged = Boolean(table.closest?.('#remediationCatalogPanel'));
      const selectedIds = new Set();
      const eligible = () => [...table.querySelectorAll('input[data-history-select]')].filter(input => !input.disabled);
      const visible = () => eligible().filter(input => !input.closest('[data-history-entry]').hidden);
      function update() {
        table.querySelectorAll('input[data-history-select]').forEach(input => {
          const entry = input.closest('[data-history-entry]');
          entry.dataset.historySelectable = String(!input.disabled);
          entry.dataset.historySelected = String(!input.disabled && input.checked);
        });
        const inputs = eligible(), shown = visible();
        if (serverPaged) inputs.forEach(input => {
          if (input.checked) selectedIds.add(input.value);
          else selectedIds.delete(input.value);
        });
        const selected = serverPaged ? selectedIds.size : inputs.filter(input => input.checked).length;
        const visibleSelected = shown.filter(input => input.checked).length;
        all.disabled = shown.length === 0;
        all.checked = shown.length > 0 && shown.length === visibleSelected;
        all.indeterminate = visibleSelected > 0 && visibleSelected < shown.length;
        button.disabled = selected === 0;
        count.hidden = selected === 0;
        count.textContent = selected ? `(${selected})` : '';
      }
      all.addEventListener('change', () => {
        visible().forEach(input => { input.checked = all.checked; });
        update();
      });
      table.addEventListener('change', update);
      table.addEventListener('click', event => {
        if (event.defaultPrevented || (event.button != null && event.button !== 0)) return;
        if (event.target.closest('a, button, input, select, textarea, label, summary, [contenteditable], [role="button"], [role="link"]')) return;
        if (env.getSelection?.()?.toString()) return;
        const entry = event.target.closest('[data-history-entry]');
        const input = entry?.querySelector('input[data-history-select]');
        if (!input || input.disabled || entry.hidden) return;
        input.checked = !input.checked;
        update();
      });
      table.addEventListener('history:filtered', update);
      table.addEventListener('history:changed', () => {
        if (serverPaged) eligible().forEach(input => { input.checked = selectedIds.has(input.value); });
        update();
      });
      form.addEventListener('submit', event => {
        update();
        if (button.disabled) event.preventDefault();
        if (serverPaged) {
          form.querySelectorAll('[data-paged-selection]').forEach(input => input.remove());
          const rendered = new Set(eligible().filter(input => input.checked).map(input => input.value));
          selectedIds.forEach(value => {
            if (rendered.has(value)) return;
            const input = env.document.createElement('input');
            input.type = 'hidden';
            input.name = 'run_ids';
            input.value = value;
            input.dataset.pagedSelection = '';
            form.append(input);
          });
        }
      });
      update();
    });
  }
  if (typeof module === 'object' && module.exports) module.exports = {init};
  else init(root);
})(typeof window === 'object' ? window : globalThis);
