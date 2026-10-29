'use strict';

// Diagnostic reads only. Detector findings, scores, DOM and scroll stay intact.
async function enrich(page, results) {
  const nodes = (results.violations || []).flatMap(violation =>
    (violation.nodes || []).slice(0, 12));
  const selectors = nodes.map(node => Array.isArray(node.target) &&
    node.target.length === 1 && typeof node.target[0] === 'string'
    ? node.target[0] : null);
  let evidence;
  try {
    evidence = await page.evaluate(selectors => selectors.map(selector => {
    if (!selector) return null;
    let element;
    try { element = document.querySelector(selector); } catch { return null; }
    if (!element) return null;
    const styles = target => {
      const css = getComputedStyle(target);
      return {color: css.color, background: css.backgroundColor, opacity: css.opacity,
        display: css.display, visibility: css.visibility, font_size: css.fontSize};
    };
    const ancestors = [];
    for (let parent = element.parentElement; parent && ancestors.length < 6;
      parent = parent.parentElement) {
      ancestors.push({element: parent.tagName.toLowerCase(), id: parent.id,
        ...styles(parent)});
    }
    return {computed_style: styles(element), ancestor_styles: ancestors};
    }), selectors);
  } catch (error) {
    results.failure_style_diagnostic = {status: 'unavailable', reason: error.message};
    return results;
  }
  nodes.forEach((node, index) => {
    if (evidence[index]) Object.assign(node, evidence[index]);
  });
  return results;
}

module.exports = {enrich};
