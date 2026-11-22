/* Restore acquired DOM topology, not HTML conformance or new link behavior. */
(() => {
  const marker = 'data-warp-frozen-nested-anchor';
  function restore() {
    for (const node of document.querySelectorAll('span[' + marker + ']')) {
      let attributes;
      try { attributes = JSON.parse(node.getAttribute(marker)); } catch { continue; }
      if (!attributes || typeof attributes !== 'object' || Array.isArray(attributes)) continue;
      const names = ['href', 'target', 'download', 'ping', 'rel', 'hreflang', 'type', 'referrerpolicy'];
      if (Object.entries(attributes).some(([key, value]) => !names.includes(key) || typeof value !== 'string')) continue;
      const anchor = document.createElement('a');
      for (const attribute of node.attributes) if (attribute.name !== marker) anchor.setAttribute(attribute.name, attribute.value);
      for (const [key, value] of Object.entries(attributes)) anchor.setAttribute(key, value);
      while (node.firstChild) anchor.appendChild(node.firstChild);
      node.replaceWith(anchor);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restore, { once: true });
  else restore();
})();
