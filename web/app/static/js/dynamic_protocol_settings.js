// Only pointer/scroll parameters depend on lazy-content activation. Load and
// stability limits still apply to every page. Disabled values stay stored.
(() => {
  const toggle = document.getElementById('enable_lazy_load_scroll');
  if (!toggle) return;
  const sync = () => document.querySelectorAll('[data-lazy-content-control]')
    .forEach(input => { input.disabled = !toggle.checked; });
  toggle.addEventListener('change', sync);
  sync();
})();
