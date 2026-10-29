/* Versioned Slick replay adapter. No origin, feed URL or site class rules. */
(() => {
  'use strict';
  const roots = new Map();
  const permitted = new WeakSet();
  function protectedNode(node) {
    return [...roots.keys()].some(root => !permitted.has(root) && (root === node || root.contains(node)));
  }
  function withPermission(root, action) {
    const alreadyPermitted = permitted.has(root);
    permitted.add(root);
    try { return action(); } finally { if (!alreadyPermitted) permitted.delete(root); }
  }
  function setup() {
    document.querySelectorAll('[data-warp-frozen-slick]').forEach(root => {
      if (!roots.has(root)) {
        try { roots.set(root, {options: JSON.parse(root.getAttribute('data-warp-slick-options')), initialized: false}); }
        catch { root.setAttribute('data-warp-replay-status', 'invalid-options'); }
      }
    });
    const $ = window.jQuery;
    if (!$ || !$.fn) return;
    // Readers remain unchanged; block reconstruction only inside frozen roots.
    // The adapter/plugin has a scoped permission while building or navigating.
    for (const name of ['empty', 'html', 'text', 'append', 'prepend', 'remove', 'detach', 'replaceWith']) {
      const original = $.fn[name];
      if (!original || original.warpFrozenGuard) continue;
      const guarded = function(...args) {
        if ((name === 'html' || name === 'text') && args.length === 0) return original.apply(this, args);
        const mutable = this.filter((_, node) => !protectedNode(node));
        if (mutable.length === this.length) return original.apply(this, args);
        if (mutable.length) original.apply(mutable, args);
        return this;
      };
      guarded.warpFrozenGuard = true;
      $.fn[name] = guarded;
    }
    const originalSlick = $.fn.slick;
    if (!originalSlick || originalSlick.warpFrozenGuard) return;
    function initialize(root, supplied = {}) {
      const state = roots.get(root);
      if (!state || state.initialized) return;
      const options = {...supplied, ...state.options};
      withPermission(root, () => originalSlick.call($(root), options));
      // Responsive rebuilds originate inside the same plugin, not a feed loader.
      for (const method of ['buildOut', 'buildRows', 'reinit', 'refresh', 'unload', 'destroy']) {
        const original = root.slick && root.slick[method];
        if (typeof original === 'function') {
          root.slick[method] = function(...args) {
            return withPermission(root, () => original.apply(this, args));
          };
        }
      }
      state.initialized = true;
      root.setAttribute('data-warp-replay-status', 'initialized');
    }
    const guardedSlick = function(...args) {
      if (!this.toArray().some(root => roots.has(root))) return originalSlick.apply(this, args);
      let result = this;
      this.each((_, root) => {
        if (!roots.has(root)) {
          const value = originalSlick.apply($(root), args);
          if (value !== undefined && !(value && value.jquery)) result = value;
        } else if (typeof args[0] === 'string') {
          initialize(root);
          const value = withPermission(root, () => originalSlick.apply($(root), args));
          if (value !== undefined && !(value && value.jquery)) result = value;
        } else initialize(root, args[0] || {});
      });
      return result;
    };
    guardedSlick.warpFrozenGuard = true;
    $.fn.slick = guardedSlick;
    // Initialize even if the original feed never completes, without a new fetch.
    if (document.readyState === 'complete') roots.forEach((_, root) => initialize(root));
    else window.addEventListener('load', () => roots.forEach((_, root) => initialize(root)), {once:true});
  }
  // Capture phase observes jQuery/plugin loading before subsequent scripts run.
  document.addEventListener('load', event => { if (event.target.tagName === 'SCRIPT') setup(); }, true);
  document.addEventListener('DOMContentLoaded', setup, {once:true});
  setup();
})();
