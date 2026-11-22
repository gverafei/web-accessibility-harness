'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { choose } = require('../frozen_resource_variants');

function asset(headers = {}, overrides = {}) {
  const body = Buffer.from('#target { color: rgb(12, 34, 56); }');
  return { url: 'https://cdn.example.test/site.css', mime: 'text/css', http_status: 200,
    body, sha256: crypto.createHash('sha256').update(body).digest('hex'), headers, ...overrides };
}

test('CORS stylesheet requests reuse an observed response with the identical bytes', () => {
  const observed = asset({ 'access-control-allow-origin': 'https://example.com',
    'access-control-allow-credentials': 'true' });
  const later = asset();
  assert.equal(choose(later, [observed, later], { Origin: 'https://example.com' }), observed);
  assert.deepEqual(observed.headers, { 'access-control-allow-origin': 'https://example.com',
    'access-control-allow-credentials': 'true' });
  assert.equal(choose(later, [observed, later], {}), later);
  assert.equal(choose(later, [observed, later], { origin: 'https://other.test' }), later);
});

test('variant selection never replaces bytes, status, MIME or protected policy', () => {
  const later = asset();
  const headers = { 'access-control-allow-origin': 'https://example.com' };
  for (const candidate of [
    asset(headers, { sha256: 'different' }),
    asset(headers, { http_status: 206 }),
    asset(headers, { mime: 'text/css; charset=iso-8859-1' }),
    asset({ ...headers, 'content-security-policy': "default-src 'none'" }),
    asset({ ...headers, 'cross-origin-resource-policy': 'same-origin' }),
  ]) assert.equal(choose(later, [candidate], { origin: 'https://example.com' }), later);
  const script = asset({}, { mime: 'application/javascript' });
  assert.equal(choose(script, [asset(headers)], { origin: 'https://example.com' }), script);
});

test('unobserved permissions stay denied and a matching selected response stays unchanged', () => {
  const denied = asset({ 'access-control-allow-origin': '' });
  assert.equal(choose(denied, [denied], { origin: 'https://example.com' }), denied);
  const observed = asset({ 'Access-Control-Allow-Origin': '*' });
  assert.equal(choose(denied, [observed], { ORIGIN: 'https://example.com' }), observed);
  assert.equal(choose(observed, [denied], { origin: 'https://example.com' }), observed);
});

test('recorded stylesheet CORS variants retain styling in the document and its iframe', async () => {
  const evidence = require('../harness_evidence');
  const originalPublicUrl = evidence.publicUrl;
  evidence.publicUrl = async value => value;
  const directory = fs.mkdtempSync('/results/css-variants-');
  try {
    const observed = asset({ 'access-control-allow-origin': 'https://example.com' });
    const later = asset();
    const child = Buffer.from('<!doctype html><html><head>' +
      '<link rel="stylesheet" crossorigin="anonymous" href="https://cdn.example.test/site.css">' +
      '</head><body><p id="target">Child</p></body></html>');
    const document = '<!doctype html><html><head><title>Recorded styles</title>' +
      '<link rel="stylesheet" crossorigin="anonymous" href="https://cdn.example.test/site.css">' +
      '</head><body><p id="target">Main</p><p id="result">Waiting</p>' +
      '<iframe id="child" src="/child"></iframe><script>addEventListener("load",()=>{' +
      'const f=document.getElementById("child");document.getElementById("result").textContent=' +
      'getComputedStyle(document.getElementById("target")).color+" / "+' +
      'f.contentWindow.getComputedStyle(f.contentDocument.getElementById("target")).color;});</script>' +
      '</body></html>';
    const manifest = { version: require('../origin_snapshot').VERSION, origin: 'https://example.com/',
      document, assets: [observed, later].map(value => ({ ...value, body: value.body.toString('base64') })).concat([
        { url: 'https://example.com/child', mime: 'text/html', body: child.toString('base64'),
          sha256: crypto.createHash('sha256').update(child).digest('hex') },
      ]), runtime_config: { enable_lazy_load_scroll: false, page_settle_delay_ms: 1,
        dom_stability_window_ms: 50, dom_stability_timeout_ms: 2000 } };
    const file = path.join(directory, 'manifest.json');
    fs.writeFileSync(file, JSON.stringify(manifest));
    const result = await require('../origin_snapshot').run(file, path.join(directory, 'out'), true);
    assert.match(result.text, /rgb\(12, 34, 56\) \/ rgb\(12, 34, 56\)/);
    assert.equal(result.live_network, false);
    assert.ok(!result.request_failures.some(request => request.url === observed.url));
    assert.equal(manifest.assets[0].sha256, manifest.assets[1].sha256);
  } finally {
    evidence.publicUrl = originalPublicUrl;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
