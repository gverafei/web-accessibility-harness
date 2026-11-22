'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const guard = require('../axe_name_guard');

test('cyclic implicit names terminate without changing ARIA or disabling rules', async () => {
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium', args:['--no-sandbox']});
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.setContent('<!doctype html><html lang="en"><title>Names</title><body><main>'
      + '<h1>Name cycles</h1><section id="self" aria-labelledby="self"><h2>Self content</h2></section>'
      + '<section id="label" aria-label="Named" aria-labelledby="label"><p>Body</p></section>'
      + '<section id="first" aria-labelledby="second"><h2>First content</h2></section>'
      + '<section id="second" aria-labelledby="first"><h2>Second content</h2></section>'
      + '<section aria-labelledby="heading"><h2 id="heading">Ordinary section</h2></section>'
      + '<button>Confirm</button></main></body></html>');
    const before = await page.content();
    const raw = await new (require('@axe-core/playwright').default)({page, axeSource:guard.source()})
      .withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa','best-practice']).analyze();
    assert.equal(await page.content(), before);
    assert.ok(raw.passes.some(rule => rule.id === 'button-name'));
    assert.equal(raw.testEngine.version, '4.13.0');
    assert.deepEqual(guard.provenance().rules_disabled, []);
    assert.equal(guard.provenance().document_modified, false);
    // Unrelated rules retain their original results on ordinary documents.
    await page.setContent('<!doctype html><html lang="en"><title>Control</title><body><main><h1>Control</h1><img src="data:,x"><button></button></main></body></html>');
    const Builder = require('@axe-core/playwright').default;
    const original = await new Builder({page}).withRules(['image-alt','button-name']).analyze();
    const patched = await new Builder({page,axeSource:guard.source()}).withRules(['image-alt','button-name']).analyze();
    const findings = result => result.violations.map(rule=>[rule.id,rule.nodes.map(n=>n.target)]);
    assert.deepEqual(findings(patched), findings(original));
  } finally { await browser.close(); }
});

test('Lighthouse loads the same guarded detector and restores filesystem reads', () => {
  const read = fs.readFileSync;
  guard.lighthouse();
  assert.equal(fs.readFileSync, read);
  const path = require('node:path');
  const root = path.dirname(require.resolve('lighthouse'));
  const {axeSource} = require(path.join(root,'lib/axe.js'));
  assert.ok(axeSource.includes('implicitNameStack'));
  assert.equal(axeSource, guard.source());
});
