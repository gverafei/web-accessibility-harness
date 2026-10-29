const test = require('node:test');
const assert = require('node:assert/strict');
const {enrich} = require('../failure_styles');

test('frozen contrast feedback includes ancestor opacity without altering detector results', async () => {
  const {chromium} = require('playwright');
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage();
    await page.setContent('<div style="opacity:.36"><button id="target" style="color:white;background:black">Play</button></div>');
    const raw = {violations: [{id: 'color-contrast', nodes: [{target: ['#target'],
      failureSummary: 'Contrast below 4.5:1', any: [{data: {contrastRatio: 3.25}}]},
      {target: ['#missing']}, {target: ['iframe', '#nested']}]}]};
    const before = await page.content();
    const originalData = JSON.stringify(raw.violations[0].nodes[0].any);
    const result = await enrich(page, raw);
    const node = result.violations[0].nodes[0];
    assert.equal(node.computed_style.opacity, '1');
    assert.equal(node.ancestor_styles[0].opacity, '0.36');
    assert.equal(JSON.stringify(node.any), originalData);
    assert.equal(await page.content(), before);
    assert.equal(await page.evaluate(() => scrollY), 0);
    assert.equal(result.violations[0].nodes[1].computed_style, undefined);
    assert.equal(result.violations[0].nodes[2].computed_style, undefined);
  } finally {
    await browser.close();
  }
});
