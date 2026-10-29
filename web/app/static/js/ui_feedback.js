/* One busy state for submissions, navigation, downloads and explicit AJAX actions. */
(function (root) {
  'use strict';
  function init(env) {
    const document = env.document;
    const host = document.getElementById('appNotifications');
    const labels = JSON.parse(document.getElementById('uiFeedbackLabels')?.textContent || '{}');
    const active = new Map(), forms = new Map();
    const restoreAttribute = (node, name, value) => value === null
      ? node.removeAttribute(name) : node.setAttribute(name, value);

    function busy(control, options = {}) {
      if (!control) return () => {};
      if (active.has(control)) return active.get(control).reset;
      const attributes = ['aria-busy', 'aria-disabled', 'aria-label'];
      const previous = attributes.map(name => control.getAttribute(name));
      const disabled = control.disabled, hadDisabledClass = control.classList.contains('disabled');
      const minWidth = control.style.minWidth;
      const icons = [...control.querySelectorAll('svg, .bi, .button-icon')]
        .filter(icon => !icon.hidden);
      const spinner = document.createElement('span');
      spinner.className = 'spinner-border spinner-border-sm button-busy-spinner';
      spinner.setAttribute('aria-hidden', 'true');
      control.style.minWidth = `${control.getBoundingClientRect().width}px`;
      icons.forEach(icon => { icon.hidden = true; });
      control.prepend(spinner);
      control.classList.add('action-busy');
      control.setAttribute('aria-busy', 'true');
      control.setAttribute('aria-disabled', 'true');
      const description = options.label || (options.download ? labels.export : labels.loading);
      if (description) control.setAttribute('aria-label', `${control.textContent.trim()} — ${description}`);
      if ('disabled' in control) control.disabled = true;
      else control.classList.add('disabled');
      const state = {download: !!options.download, started: Date.now(), reset};
      function reset() {
        if (active.get(control) !== state) return;
        env.clearTimeout(state.timer);
        env.clearInterval(state.poll);
        spinner.remove();
        icons.forEach(icon => { icon.hidden = false; });
        control.style.minWidth = minWidth;
        control.classList.remove('action-busy');
        if (!hadDisabledClass) control.classList.remove('disabled');
        attributes.forEach((name, index) => restoreAttribute(control, name, previous[index]));
        if ('disabled' in control) control.disabled = disabled;
        active.delete(control);
        state.onReset?.();
      }
      active.set(control, state);
      if (options.download) state.timer = env.setTimeout(reset, 45000);
      return reset;
    }

    function trackDownload(control, applyToken, restore) {
      const state = active.get(control);
      const token = [...env.crypto.getRandomValues(new Uint8Array(16))]
        .map(byte => byte.toString(16).padStart(2, '0')).join('');
      const cookie = `warp_download_${token}`;
      applyToken(token);
      state.tracked = true;
      const previousReset = state.onReset;
      state.onReset = () => {
        restore();
        document.cookie = `${cookie}=; Max-Age=0; Path=/; SameSite=Lax`;
        previousReset?.();
      };
      // Set by the server when attachment headers are ready: the browser can
      // open Save As now, independently of saving/canceling or streaming bytes.
      state.poll = env.setInterval(() => {
        const signal = document.cookie.split(';').map(value => value.trim())
          .find(value => value.startsWith(`${cookie}=`));
        if (signal === `${cookie}=ready` || signal === `${cookie}=error`) state.reset();
      }, 100);
    }

    function notify(message, category = 'success') {
      if (!host) return;
      const alert = document.createElement('div');
      category = ['success', 'danger', 'warning', 'info'].includes(category) ? category : 'info';
      alert.className = `alert alert-${category} alert-dismissible fade show`;
      alert.setAttribute('role', category === 'danger' ? 'alert' : 'status');
      alert.setAttribute('tabindex', '-1');
      const text = document.createElement('span');
      text.textContent = message;
      const close = document.createElement('button');
      close.type = 'button'; close.className = 'btn-close';
      close.setAttribute('data-bs-dismiss', 'alert');
      close.setAttribute('aria-label', labels.close || 'Close');
      alert.append(text, close);
      host.replaceChildren(alert);
      // Match the upper flash reached after a General save, retaining the active tab.
      alert.scrollIntoView({block: 'nearest', behavior: 'auto'});
      alert.focus({preventScroll: true});
    }

    document.addEventListener('submit', event => {
      const form = event.target;
      if (event.defaultPrevented || form.method === 'dialog' || form.dataset.busy === 'off' ||
          (form.target && form.target !== '_self')) return;
      if (forms.has(form)) { event.preventDefault(); return; }
      if (!form.noValidate && !event.submitter?.formNoValidate && !form.checkValidity()) return;
      const control = event.submitter || document.getElementById(form.dataset.busyControl) ||
        [...form.elements].find(item => item.type === 'submit' && !item.disabled);
      if (!control) return;
      // Disabled submitters are not successful controls. Preserve their action value.
      let value;
      if (control.name) {
        value = document.createElement('input');
        value.type = 'hidden'; value.name = control.name; value.value = control.value;
        form.append(value);
      }
      const reset = busy(control, {download: form.hasAttribute('data-busy-download')});
      forms.set(form, reset);
      active.get(control).onReset = () => { value?.remove(); forms.delete(form); };
      if (form.hasAttribute('data-busy-download')) {
        let tokenField;
        trackDownload(control, token => {
          tokenField = document.createElement('input');
          tokenField.type = 'hidden'; tokenField.name = '_download_token'; tokenField.value = token;
          form.append(tokenField);
        }, () => tokenField.remove());
      }
      if (form.hasAttribute('data-busy-navigation')) {
        // Native navigation can freeze the outgoing document before its next
        // paint. Let the spinner render before starting the POST; do not
        // redispatch submit (which would repeat validation/confirmation hooks).
        event.preventDefault();
        const overrides = ['action', 'method', 'enctype', 'target'];
        const previous = overrides.map(name => form.getAttribute(name));
        overrides.forEach(name => {
          const override = control.getAttribute(`form${name}`);
          if (override !== null) form.setAttribute(name, override);
        });
        env.requestAnimationFrame(() => env.requestAnimationFrame(() => {
          if (!forms.has(form)) return;
          try { env.HTMLFormElement.prototype.submit.call(form); }
          catch (error) { reset(); throw error; }
          finally { overrides.forEach((name, index) => restoreAttribute(form, name, previous[index])); }
        }));
      }
    });
    document.addEventListener('click', event => {
      const link = event.target.closest('a.btn, a.history-action, a.experiment-action, a.dataset-report-action');
      if (!link) return;
      if (active.has(link)) { event.preventDefault(); return; }
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey ||
          event.shiftKey || event.altKey || link.dataset.busy === 'off' ||
          link.classList.contains('disabled') || link.getAttribute('aria-disabled') === 'true' ||
          (link.target && link.target !== '_self') || link.hasAttribute('data-bs-toggle')) return;
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#')) return;
      const destination = new URL(href, env.location.href);
      if (destination.origin !== env.location.origin || !['http:', 'https:'].includes(destination.protocol)) return;
      if (destination.pathname === env.location.pathname && destination.search === env.location.search && destination.hash) return;
      const download = link.hasAttribute('download') || link.classList.contains('warp-export');
      busy(link, {download});
      if (download) trackDownload(link, token => {
        destination.searchParams.set('_download_token', token);
        link.setAttribute('href', destination.href);
      }, () => link.setAttribute('href', href));
    });
    env.addEventListener('pageshow', () => [...active.values()].forEach(item => item.reset()));
    env.addEventListener('focus', () => [...active.values()].forEach(item => {
      if (item.download && !item.tracked && Date.now() - item.started > 1500) item.reset();
    }));
    return {busy, notify};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {init};
  else {
    const feedback = init(root);
    root.warpButtonBusy = feedback.busy;
    root.warpNotify = feedback.notify;
  }
})(typeof window !== 'undefined' ? window : globalThis);
