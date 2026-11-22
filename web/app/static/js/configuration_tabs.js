/* Tab state is not a DOM anchor: saving/reloading must not jump to a panel. */
(function (root) {
  function init(env) {
    const document = env.document;
    const general = document.getElementById('configurationGeneralTab');
    const modelTab = document.getElementById('configurationModelsTab');
    const editor = document.getElementById('modelCatalogEditor');
    const models = editor?.dataset?.kind === 'decisions' ? document.getElementById('configurationDecisionsTab') : modelTab;
    if (!general || !models) return;
    const legacy = ['#configurationGeneral', '#configurationModels', '#modelCatalogEditor'];
    const initialLegacy = legacy.includes(env.location.hash);
    const canonical = tab => tab === models ? '#models' : '#general';
    const remember = tab => env.history.replaceState(null, '', canonical(tab));
    const selectFromHash = () => {
      const hash = env.location.hash;
      const target = document.getElementById(hash.slice(1));
      const modelTab = hash === '#models' || hash === '#configurationModels' ||
        hash === '#modelCatalogEditor' || target?.closest('#configurationModels');
      const tab = modelTab ? models : general;
      env.bootstrap.Tab.getOrCreateInstance(tab).show();
      if (legacy.includes(hash) || hash === '#models' || hash === '#general' || !hash) {
        remember(tab);
        if (legacy.includes(hash)) {
          // Undo the browser's initial anchor jump for old bookmarked URLs.
          env.scrollTo({top: 0, behavior: 'instant'});
          env.requestAnimationFrame(() => env.scrollTo({top: 0, behavior: 'instant'}));
        }
      } else if (target) target.scrollIntoView({block: 'start'});
    };
    [general, models].forEach(tab => tab.addEventListener('shown.bs.tab', () => remember(tab)));
    env.addEventListener('hashchange', selectFromHash);
    if (initialLegacy) env.addEventListener('pageshow', () => {
      // History restoration may occur after the first animation frame on F5.
      env.scrollTo({top: 0, behavior: 'instant'});
      env.requestAnimationFrame(() => env.scrollTo({top: 0, behavior: 'instant'}));
    }, {once: true});
    selectFromHash();
    return {selectFromHash};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {init};
  else init(root);
})(typeof window !== 'undefined' ? window : globalThis);
