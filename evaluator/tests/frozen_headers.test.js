'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { entries, routeHeaders } = require('../frozen_headers');

const policies = "script-src 'unsafe-inline'\nscript-src 'none'";

test('repeated CSP policies become separate Chromium entries without relaxing either', () => {
  assert.deepEqual(entries({ 'content-security-policy': policies }), [
    { name: 'content-security-policy', value: "script-src 'unsafe-inline'" },
    { name: 'content-security-policy', value: "script-src 'none'" },
  ]);
  assert.equal(routeHeaders({ 'content-security-policy': policies })['content-security-policy'],
    "script-src 'unsafe-inline', script-src 'none'");
});

test('ordinary headers are preserved, while unexpected CR or multiline fields fail', () => {
  const headers = { 'content-type': 'text/html', 'cross-origin-resource-policy': 'same-site' };
  assert.deepEqual(routeHeaders(headers), headers);
  assert.throws(() => entries({ 'content-security-policy': "default-src 'self'\r\nother" }), /carriage return/);
  assert.throws(() => entries({ 'access-control-allow-origin': 'https://one.test\nhttps://two.test' }), /Unsupported repeated/);
  assert.throws(() => entries({ 'content-security-policy': policies + '\n' }), /Empty frozen/);
});

test('empty ordinary response headers remain present without changing their value', () => {
  const headers = { 'access-control-allow-origin': '', 'x-recorded-header': '' };
  assert.deepEqual(entries(headers), [
    { name: 'access-control-allow-origin', value: '' },
    { name: 'x-recorded-header', value: '' },
  ]);
  assert.deepEqual(routeHeaders(headers), headers);
});

test('frozen iframe renders its actual control while both CSP policies still block inline script', async () => {
  const evidence = require('../harness_evidence');
  const originalPublicUrl = evidence.publicUrl;
  evidence.publicUrl = async value => value;
  const directory = fs.mkdtempSync('/results/repeated-csp-');
  try {
    const body = Buffer.from('<!doctype html><html><body><button>Continue with provider</button>' +
      '<p id="effect">blocked</p><script>document.getElementById("effect").textContent="executed"</script></body></html>');
    const document = '<!doctype html><html><body><h1 id="result">Waiting</h1>' +
      '<iframe id="frame" src="/widget"></iframe><script>' +
      'const frame=document.getElementById("frame");frame.onload=()=>{' +
      'const child=frame.contentDocument;document.getElementById("result").textContent=' +
      '(child.querySelector("button")?.textContent||"missing")+" / "+' +
      '(child.getElementById("effect")?.textContent||"missing");};</script></body></html>';
    const manifest = {
      version: require('../origin_snapshot').VERSION,
      origin: 'https://example.com/', document,
      assets: [{ url: 'https://example.com/widget', mime: 'text/html',
        body: body.toString('base64'), sha256: crypto.createHash('sha256').update(body).digest('hex'),
        headers: { 'content-security-policy': policies, 'access-control-allow-origin': '' } }],
      runtime_config: { enable_lazy_load_scroll: false, page_settle_delay_ms: 1,
        dom_stability_window_ms: 50, dom_stability_timeout_ms: 2000 },
    };
    const file = path.join(directory, 'manifest.json');
    fs.writeFileSync(file, JSON.stringify(manifest));
    const result = await require('../origin_snapshot').run(file, path.join(directory, 'out'), true);
    assert.match(result.text, /Continue with provider \/ blocked/);
    assert.equal(result.live_network, false);
    assert.ok(!result.script_errors.some(message => message.includes('Invalid header')));
    assert.ok(!result.request_failures.some(request => request.url.endsWith('/widget')));
  } finally {
    evidence.publicUrl = originalPublicUrl;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
