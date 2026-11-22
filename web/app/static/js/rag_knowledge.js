/* Corpus maintenance is explicit, independent of saving general settings. */
(function (root) {
  function init(panel, options = {}) {
    if (!panel) return;
    const fetcher = options.fetch || root.fetch.bind(root);
    const confirm = options.confirm || root.warpConfirm;
    const timer = options.setTimeout || root.setTimeout;
    const clear = options.clearTimeout || root.clearTimeout;
    const observeCorpus = options.observeCorpus || (version => root.dispatchEvent(
      new root.CustomEvent('rag-corpus-observed', {detail:{version}})));
    const labels = JSON.parse(panel.dataset.labels);
    const get = id => panel.querySelector('#' + id);
    const button = get('ragSynchronize');
    let current, polling, requesting = false, disposed = false, revision = 0;
    const text = (id, value) => { get(id).textContent = value; };
    async function request(url, options = {}) {
      const controller = new AbortController();
      const timeout = timer(() => controller.abort(), 15000);
      try {
        const response = await fetcher(url, {...options, signal: controller.signal});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || labels.loadError);
        return data;
      } finally { clear(timeout); }
    }
    function render(data) {
      const c = data.corpus, job = data.job || {};
      const busy = ['queued', 'running'].includes(job.status);
      const hasExamples = c.count > 0;
      text('ragCorpusStatus', !c.reachable ? labels.unavailable : hasExamples ? labels.available : labels.empty);
      text('ragOfficialCount', c.official == null ? '—' : String(c.official));
      text('ragComplementaryCount', c.complementary == null ? '—' : String(c.complementary));
      text('ragSyncDate', c.synchronized_at ? new Date(c.synchronized_at).toLocaleString() : labels.unknown);
      text('ragSynchronizeLabel', hasExamples ? labels.update : labels.initialize);
      text('ragBlockedReason', data.active_runs > 0 ? labels.blocked : '');
      button.disabled = requesting || busy || !c.reachable || data.active_runs > 0;
      const progress = get('ragSyncProgress');
      progress.hidden = !busy;
      const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
      progress.querySelector('[role="progressbar"]').setAttribute('aria-valuenow', percent);
      progress.querySelector('.progress-bar').style.width = percent + '%';
      let message = labels[job.phase] || '';
      if (job.status === 'failed') message = job.error?.includes('interrupted') ? labels.interrupted : labels.syncError;
      text('ragSyncMessage', message);
      if (!disposed && !busy && c.reachable && c.synchronized_at) observeCorpus(c.synchronized_at);
      clear(polling);
      // Poll even when idle, so a run queued in another tab disables maintenance.
      if (!disposed) polling = timer(load, busy ? 2000 : 10000);
    }
    async function load() {
      if (requesting || disposed) return;
      const mine = ++revision;
      clear(polling);
      try {
        const data = await request(panel.dataset.statusUrl);
        if (disposed || mine !== revision) return;
        current = data;
        render(data);
      } catch (_) {
        if (disposed || mine !== revision) return;
        button.disabled = true;
        text('ragSyncMessage', labels.loadError);
        polling = timer(load, 10000);
      }
    }
    button.addEventListener('click', async () => {
      if (button.disabled || requesting || !current) return;
      requesting = true; button.disabled = true;
      ++revision; // Discard any GET started before this explicit action.
      clear(polling);
      const mode = current.corpus.count > 0 ? 'update' : 'initialize';
      let done;
      try {
        if (mode === 'update' && !await confirm(labels.confirm, {confirmLabel: labels.update})) {
          return;
        }
        done = root.warpButtonBusy?.(button);
        const data = await request(panel.dataset.syncUrl, {method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({mode, confirmed:mode === 'update'})});
        if (disposed) return;
        current.job = data.job;
        render(current);
      } catch (error) { if (!disposed) text('ragSyncMessage', error.message || labels.loadError); }
      finally {
        done?.();
        requesting = false;
        // Retain any POST error until refresh; recheck state before another action.
        button.disabled = true;
        if (!disposed) polling = timer(load, 2000);
      }
    });
    load();
    return {load, render, dispose() { disposed = true; ++revision; clear(polling); }};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {init};
  else {
    const controller = init(document.getElementById('ragKnowledge'));
    root.addEventListener('pagehide', () => controller?.dispose(), {once:true});
  }
})(typeof window !== 'undefined' ? window : globalThis);
