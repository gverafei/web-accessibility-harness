(() => {
  const language = document.querySelector('[data-language-switch]');
  if (language) {
    language.addEventListener('click', () => {
      const destination = new URL(language.href, window.location.href);
      const location = window.location;
      destination.searchParams.set('next', location.pathname + location.search + location.hash);
      language.href = destination.href;
    });
  }

  const dock = document.getElementById('commandDock');
  const dockToggle = document.getElementById('dockToggle');
  if (dock && dockToggle) {
    const setHidden = hidden => {
      dock.hidden = hidden;
      dockToggle.setAttribute('aria-expanded', String(!hidden));
      const label = hidden ? dockToggle.dataset.showLabel : dockToggle.dataset.hideLabel;
      dockToggle.setAttribute('aria-label', label);
      dockToggle.title = `${label} · Ctrl/⌘+Shift+M`;
      try { window.localStorage.setItem('harness.navigation.hidden', String(hidden)); } catch (_) {}
    };
    let hidden = false;
    try { hidden = window.localStorage.getItem('harness.navigation.hidden') === 'true'; } catch (_) {}
    setHidden(hidden);
    dockToggle.addEventListener('click', () => setHidden(!dock.hidden));
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'm') {
        event.preventDefault();
        setHidden(!dock.hidden);
        dockToggle.focus();
      }
    });
  }

  const button = document.getElementById('commandMenuButton');
  const menu = document.getElementById('commandMenu');
  if (menu && button) {
    const open = () => menu.showModal();
    button.addEventListener('click', open);
    menu.querySelector('[data-command-close]').addEventListener('click', () => menu.close());
    menu.addEventListener('click', event => { if (event.target === menu) menu.close(); });
    menu.addEventListener('close', () => (dock?.hidden ? dockToggle : button).focus());
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); if (menu.open) menu.close(); else open();
      }
    });
  }
  const strategy = document.getElementById('launchStrategy');
  const hint = document.getElementById('adaptiveHelp');
  if (strategy && hint) {
    const update = () => { hint.hidden = strategy.value !== 'P5'; };
    strategy.addEventListener('change', update); update();
  }
  const progress = document.querySelector('[data-submission-status]');
  if (progress) {
    const message = progress.querySelector('[data-submission-message]');
    const poll = async () => {
      try {
        const response = await fetch(progress.dataset.submissionStatus, {
          headers: {Accept: 'application/json'}, cache: 'no-store',
          signal: window.AbortSignal?.timeout(12000),
        });
        if (!response.ok) throw new Error('Status unavailable');
        const state = await response.json();
        if (state.destination) {
          const destination = new URL(state.destination, window.location.href);
          if (destination.origin !== window.location.origin) throw new Error('Invalid report destination');
          window.location.replace(destination.href);
          return;
        }
        if (message.textContent !== state.message) message.textContent = state.message;
        progress.dataset.status = state.status;
        if (state.phase) {
          progress.dataset.phase = state.phase;
          progress.querySelectorAll('[data-preparation-step]').forEach(step => {
            if (step.dataset.preparationStep === state.phase) step.setAttribute('aria-current', 'step');
            else step.removeAttribute('aria-current');
          });
        }
        if (state.status === 'failed') {
          progress.setAttribute('role', 'alert');
          progress.setAttribute('aria-busy', 'false');
          const submit = document.querySelector('#launchForm button[type="submit"]');
          if (submit) submit.disabled = false;
          return;
        }
        setTimeout(poll, 2000);
      } catch (_) {
        message.textContent = progress.dataset.connectionMessage;
        setTimeout(poll, 5000);
      }
    };
    if (progress.dataset.status !== 'failed') poll();
  }
})();
