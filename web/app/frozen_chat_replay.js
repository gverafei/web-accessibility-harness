/* Preserve recognized captured SDK markup while its original handlers rebind. */
(() => {
  'use strict';
  const selector = '.ochat_slideout[data-trackas="ochat_slideout"], #ochat_modal.ochat_modal[data-trackas="ochat-modal"], #oReactiveChatContainer';
  function setup() {
    const $ = window.jQuery, roots = [...document.querySelectorAll(selector)];
    if (!$ || !$.fn || roots.length < 2 || roots.length > 3) return;
    const protectedNode = node => roots.some(root => root === node || root.contains(node));
    for (const name of ['append', 'prepend']) {
      const original = $.fn[name];
      if (!original || original.warpFrozenChatGuard) continue;
      const guarded = function(...args) {
        // Outside captured roots all ordinary insertions remain available, except
        // recreating the two proven SDK roots under body (same loader pattern).
        const permitted = this.filter((_, node) => !protectedNode(node));
        const filtered = args.map(value => {
          if (typeof value === 'function') return value;
          if (typeof value !== 'string' && !(value && (value.jquery || value.nodeType))) return value;
          const nodes = typeof value === 'string' ? $.parseHTML(value, document, true) : value.jquery ? value.toArray() : [value];
          return $(nodes || []).filter((_, node) => !node.matches?.(selector));
        });
        if (permitted.length) original.apply(permitted, filtered);
        return this;
      };
      guarded.warpFrozenChatGuard = true;
      $.fn[name] = guarded;
    }
    roots.forEach(root => root.setAttribute('data-warp-chat-replay-status', 'construction-guarded'));
  }
  document.addEventListener('load', event => { if (event.target.tagName === 'SCRIPT') setup(); }, true);
  document.addEventListener('DOMContentLoaded', setup, {once:true});
  setup();
})();
