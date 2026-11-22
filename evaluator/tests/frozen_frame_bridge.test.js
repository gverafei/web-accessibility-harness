'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const bridge = require('../frozen_frame_bridge');

const widgetUrl = 'https://accounts.google.com/gsi/button?iframe_id=gsi_test_1&client_id=observed-client';

function widget({id = 'gsi_test_1', extraCommand = false} = {}) {
  return `<html><body><div id="container-div"></div><script>
    addEventListener('message', event => {
      if (event.origin !== 'https://example.com' || event.data?.type !== 'channelConnect') return;
      const port = event.ports[0];
      document.getElementById('container-div').innerHTML =
        '<button style="width:400px;height:40px">Continue with Google</button>';
      port.postMessage({type:'command',command:'resize',iframeId:'${id}',width:420,height:44});
      ${extraCommand ? "port.postMessage({type:'command',command:'clicked',credential:'never-authorize'});" : ''}
    });
    parent.postMessage({type:'readyForConnect',iframeId:'${id}'}, 'https://example.com');
  </script></body></html>`;
}

function source(url = widgetUrl, id = 'gsi_test_1') {
  return '<html><body><h1>Captured source</h1><iframe id="' + id + '" src="' + url
    + '" style="width:420px;height:44px"></iframe></body></html>';
}

test('only recorded Google button documents with bounded IDs enter the allowlist', () => {
  assert.equal(bridge.buttonIdentity('https://evil.test/gsi/button?iframe_id=gsi_test_1'), null);
  assert.equal(bridge.buttonIdentity('https://accounts.google.com/other?iframe_id=gsi_test_1'), null);
  assert.equal(bridge.buttonIdentity('https://accounts.google.com/gsi/button?iframe_id=wrong'), null);
  assert.equal(bridge.buttonIdentity('https://user@accounts.google.com/gsi/button?iframe_id=gsi_test_1'), null);
  assert.deepEqual(bridge.recordedButtons(new Map([[widgetUrl, {mime:'text/html; charset=utf-8'}]])),
    [{url:widgetUrl,id:'gsi_test_1'}]);
  assert.deepEqual(bridge.recordedButtons(new Map([[widgetUrl, {mime:'application/javascript'}]])), []);
  const many = new Map(Array.from({length:65}, (_, i) =>
    ['https://accounts.google.com/gsi/button?iframe_id=gsi_' + i, {mime:'text/html'}]));
  assert.throws(() => bridge.recordedButtons(many), /limit exceeded/);
});

async function browserFixture(callback, {child = widget(), assets = true, document = source()} = {}) {
  const {chromium} = require('playwright');
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    args:['--no-sandbox','--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => {
      const url = route.request().url();
      if (url === 'https://example.com/') return route.fulfill({contentType:'text/html',body:'<html><body></body></html>'});
      if (url === widgetUrl) return route.fulfill({contentType:'text/html',body:child});
      return route.abort();
    });
    await page.goto('https://example.com/');
    const allowed = assets ? new Map([[widgetUrl,{mime:'text/html'}]]) : new Map();
    await bridge.install(page, allowed);
    await require('../native_media_pause').write(page, document);
    await callback(page, allowed);
  } finally { await browser.close(); }
}

test('the recorded iframe renders its own button after document.open, without changing captured geometry or accepting auth commands', async () => {
  await browserFixture(async (page, assets) => {
    const settled = await bridge.settle(page, assets);
    assert.equal(settled.status, 'settled');
    assert.equal(settled.frames[0].controls[0].width, 400);
    const record = settled.bridge.connections[0];
    assert.equal(record.id, 'gsi_test_1');
    assert.equal(record.resize_messages, 1);
    assert.equal(record.ignored_commands, 1);
    assert.deepEqual(record.rendered_dimensions, {width:420,height:44});
    assert.equal(await page.locator('iframe').getAttribute('style'), 'width:420px;height:44px');
    assert.equal(page.url(), 'https://example.com/');
    const before = await bridge.freeze(page);
    const child = page.frames().find(frame => frame.url() === widgetUrl);
    await child.evaluate(() => parent.postMessage({type:'readyForConnect',iframeId:'gsi_test_1'}, 'https://example.com'));
    await page.waitForTimeout(50);
    assert.deepEqual(await bridge.snapshot(page), before);
  }, {child:widget({extraCommand:true})});
});

test('a mismatched ID cannot obtain a port or turn a blank iframe into a settled measurement', async () => {
  await browserFixture(async (page, assets) => {
    await assert.rejects(bridge.settle(page, assets, {timeoutMs:100}), error =>
      error.frame_bridge.status === 'incomplete');
    const evidence = await bridge.snapshot(page);
    assert.equal(evidence.connections.length, 0);
    assert.equal(evidence.rejected_messages, 1);
  }, {child:widget({id:'gsi_other'})});
});

test('an unrecorded frame and a forged Window event receive no bridge', async () => {
  await browserFixture(async page => {
    await page.waitForTimeout(100);
    assert.equal(await bridge.snapshot(page), null);
    const frame = page.frames().find(frame => frame.url() === widgetUrl);
    assert.equal(await frame.locator('#container-div button').count(), 0);
  }, {assets:false});
  await browserFixture(async (page, assets) => {
    await page.evaluate(() => {
      const frame = document.querySelector('iframe');
      dispatchEvent(new MessageEvent('message', {origin:'https://accounts.google.com',
        source:frame.contentWindow, data:{type:'readyForConnect',iframeId:frame.id}}));
    });
    await page.waitForTimeout(100);
    assert.equal((await bridge.snapshot(page)).connections.length, 0);
    await assert.rejects(bridge.settle(page, assets, {timeoutMs:100}));
  }, {child:'<html><body><div id="container-div"></div></body></html>'});
});

test('an executable parent Google client keeps its own channel initialization', async () => {
  const document = source() + '<script src="https://accounts.google.com/gsi/client"></script>';
  await browserFixture(async (page, assets) => {
    await assert.rejects(bridge.settle(page, assets, {timeoutMs:100}));
    assert.equal((await bridge.snapshot(page)).connections.length, 0);
  }, {document});
});

test('origin replay settles the widget before freezing its measurement state', async () => {
  const evidence = require('../harness_evidence');
  const original = evidence.publicUrl;
  evidence.publicUrl = async value => value;
  const directory = fs.mkdtempSync('/results/google-button-bridge-');
  try {
    const body = Buffer.from(widget());
    const manifest = {version:require('../origin_snapshot').VERSION, origin:'https://example.com/',
      document:source(), assets:[{url:widgetUrl,mime:'text/html',body:body.toString('base64'),
        sha256:crypto.createHash('sha256').update(body).digest('hex')}],
      runtime_config:{enable_lazy_load_scroll:false,page_settle_delay_ms:1,
        dom_stability_window_ms:50,dom_stability_timeout_ms:2000}};
    const file = path.join(directory,'manifest.json');
    fs.writeFileSync(file,JSON.stringify(manifest));
    const result = await require('../origin_snapshot').run(file,path.join(directory,'out'),true);
    assert.equal(result.frame_initialization.status,'settled');
    assert.equal(result.frozen_frame_bridge.frozen,true);
    assert.equal(result.frame_initialization.frames[0].controls[0].width,400);
    assert.equal(result.live_network,false);
  } finally {
    evidence.publicUrl = original;
    fs.rmSync(directory,{recursive:true,force:true});
  }
});
