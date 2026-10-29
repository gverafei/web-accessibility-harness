/* Both histories use the same records, controls and optional display preference. */
(function (root) {
  const key = 'history-list-view';
  function restore(env = root) {
    let mode = 'table';
    try { if (env.localStorage.getItem(key) === 'cards') mode = 'cards'; } catch (_) {}
    env.document.documentElement.dataset.historyView = mode;
    return mode;
  }
  function init(env = root) {
    const controls = [...env.document.querySelectorAll('[data-history-view-controls]')];
    const mode = restore(env);
    function apply(next) {
      if (!['table', 'cards'].includes(next)) return;
      env.document.documentElement.dataset.historyView = next;
      controls.forEach(control => {
        const view = env.document.getElementById(control.dataset.historyViewControls);
        if (!view) return;
        view.dataset.historyView = next;
        control.querySelectorAll('[data-history-mode]').forEach(button =>
          button.setAttribute('aria-pressed', String(button.dataset.historyMode === next)));
      });
    }
    apply(mode);
    controls.forEach(control => control.addEventListener('click', event => {
      const button = event.target.closest('[data-history-mode]');
      if (!button || !control.contains(button)) return;
      const next = button.dataset.historyMode;
      if (!['table', 'cards'].includes(next)) return;
      apply(next);
      try { env.localStorage.setItem(key, next); } catch (_) {}
    }));
  }
  if (typeof module === 'object' && module.exports) module.exports = {init, restore};
  else {
    // Run in the head: CSS sees the saved mode before any list can be painted.
    restore(root);
    if (root.document.readyState === 'loading')
      root.document.addEventListener('DOMContentLoaded', () => init(root), {once: true});
    else init(root);
  }
})(typeof window === 'object' ? window : globalThis);
