'use strict';

const VERSION = 'frozen-google-button-channel-v1';
const MAX_FRAMES = 64;
const GOOGLE_ORIGIN = 'https://accounts.google.com';

function buttonIdentity(value) {
  try {
    const url = new URL(value);
    const id = url.searchParams.get('iframe_id');
    if (url.origin !== GOOGLE_ORIGIN || url.pathname !== '/gsi/button'
        || url.username || url.password || !/^gsi_[A-Za-z0-9_]{1,120}$/.test(id || '')) {
      return null;
    }
    return {url: url.href, id};
  } catch {
    return null;
  }
}

function recordedButtons(assets) {
  const result = [];
  for (const [url, asset] of assets) {
    const identity = buttonIdentity(url);
    if (identity && asset.mime?.split(';')[0] === 'text/html') result.push(identity);
  }
  if (result.length > MAX_FRAMES) throw Error('Frozen button frame limit exceeded');
  return result;
}

async function install(page, assets) {
  const buttons = recordedButtons(assets);
  if (!buttons.length) return;
  await page.evaluate(({buttons, version}) => {
    const allowed = new Map(buttons.map(button => [button.url, button.id]));
    const connections = new Map();
    let stopped = false;
    let rejected = 0;

    function connect(event) {
      if (stopped || !event.isTrusted || event.origin !== 'https://accounts.google.com'
          || event.data?.type !== 'readyForConnect') return;
      const frames = [...document.querySelectorAll('iframe')];
      const frame = frames.find(element => element.contentWindow === event.source);
      if (!frame || allowed.get(frame.src) !== frame.id || event.data.iframeId !== frame.id
          || frames.filter(element => element.id === frame.id).length !== 1) {
        rejected++;
        return;
      }
      // An authored, executable Google client retains its own initialization.
      // The bridge supplies the missing parent side only for acquired DOM replay.
      const activeClient = [...document.scripts].some(script => {
        try {
          const url = new URL(script.src);
          return url.origin === event.origin && url.pathname === '/gsi/client'
            && ['', 'text/javascript', 'application/javascript', 'module'].includes(script.type);
        } catch { return false; }
      });
      if (activeClient || connections.has(frame)) return;
      const channel = new MessageChannel();
      const record = {id: frame.id, connected: true, resize_messages: 0,
        ignored_commands: 0, rendered_dimensions: null, port: channel.port1};
      connections.set(frame, record);
      channel.port1.onmessage = message => {
        if (stopped) return;
        const data = message.data;
        if (data?.type === 'command' && data.command === 'resize'
            && data.iframeId === frame.id && Number.isFinite(data.width)
            && Number.isFinite(data.height) && data.width > 0 && data.width <= 2000
            && data.height > 0 && data.height <= 1000) {
          record.resize_messages++;
          record.rendered_dimensions = {width: data.width, height: data.height};
        } else {
          record.ignored_commands++;
        }
      };
      channel.port1.start();
      // No credentials, authentication success, DOM replacement or navigation
      // response is supplied. The recorded Google body renders its own control.
      event.source.postMessage({type: 'channelConnect'}, event.origin, [channel.port2]);
    }

    function reset() {
      for (const record of connections.values()) record.port.close();
      connections.clear();
      stopped = false;
      window.addEventListener('message', connect);
    }

    const open = document.open;
    document.open = function(...args) {
      const result = Reflect.apply(open, this, args);
      if (args.length < 3) reset();
      return result;
    };
    reset();
    Object.defineProperty(window, '__harnessFrozenFrameBridge', {
      value: Object.freeze({
        freeze: () => { stopped = true; },
        snapshot: () => ({version, scope: 'recorded-button-render-initialization',
          frozen: stopped, rejected_messages: rejected,
          connections: [...connections.values()].map(({port, ...record}) => record)}),
      }),
      configurable: false,
    });
  }, {buttons, version: VERSION});
}

async function settle(page, assets, {timeoutMs = 4000} = {}) {
  const allowed = recordedButtons(assets);
  if (!allowed.length) return {version: VERSION, status: 'not_applicable', frames: []};
  const expected = await page.evaluate(buttons => {
    const known = new Map(buttons.map(button => [button.url, button.id]));
    return [...document.querySelectorAll('iframe')].filter(frame => {
      const rect = frame.getBoundingClientRect();
      return known.get(frame.src) === frame.id && rect.width > 0 && rect.height > 0
        && getComputedStyle(frame).visibility !== 'hidden';
    }).map(frame => ({id: frame.id, url: frame.src}));
  }, allowed);
  const deadline = Date.now() + timeoutMs;
  let observed = [];
  do {
    observed = [];
    for (const item of expected) {
      const frame = page.frames().find(frame => frame.url() === item.url);
      let controls = [];
      try {
        if (frame) controls = await frame.evaluate(() =>
          [...document.querySelectorAll('#container-div button, #container-div [role="button"]')]
            .map(element => {
              const rect = element.getBoundingClientRect();
              return {width: rect.width, height: rect.height,
                named: !!(element.getAttribute('aria-label')
                  || element.textContent.trim()),
                visible: rect.width > 0 && rect.height > 0
                  && getComputedStyle(element).visibility !== 'hidden'};
            }));
      } catch { /* Navigation can replace the child execution context while loading. */ }
      observed.push({id: item.id, controls});
    }
    if (observed.every(item => item.controls.some(control => control.visible && control.named))) {
      return {version: VERSION, status: 'settled', frames: observed,
        bridge: await snapshot(page)};
    }
    await page.waitForTimeout(100);
  } while (Date.now() < deadline);
  const error = Error('Recorded sign-in button did not finish render initialization');
  error.frame_bridge = {version: VERSION, status: 'incomplete', frames: observed,
    bridge: await snapshot(page)};
  throw error;
}

async function snapshot(page) {
  return page.evaluate(() => window.__harnessFrozenFrameBridge?.snapshot() || null);
}

async function freeze(page) {
  await page.evaluate(() => window.__harnessFrozenFrameBridge?.freeze());
  return snapshot(page);
}

module.exports = {VERSION, buttonIdentity, recordedButtons, install, settle, snapshot, freeze};
