const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/workspace.js'), 'utf8');

test('language changes retain filters updated locally and the current report anchor', () => {
  let click;
  const language = {href: '/language/es?next=/remediation/',
    addEventListener(event, callback) {assert.equal(event, 'click'); click = callback;}};
  const document = {getElementById: () => null,
    querySelector: selector => selector === '[data-language-switch]' ? language : null};
  const location = {href: 'http://localhost:5088/remediation/', pathname: '/remediation/',
    search: '', hash: ''};
  vm.runInNewContext(source, {document, window: {location}, URL});
  location.search = '?remediationListFilterQuery=1326&remediationListFilterPage=2';
  location.hash = '#iteration-3112';
  click();
  const destination = new URL(language.href);
  assert.equal(destination.pathname, '/language/es');
  assert.equal(destination.searchParams.get('next'),
    '/remediation/?remediationListFilterQuery=1326&remediationListFilterPage=2#iteration-3112');
});

function dockFixture(saved) {
  const storage = new Map(saved ? [['harness.navigation.hidden', saved]] : []);
  const handlers = {}, listeners = {};
  const dock = {hidden: false};
  const label = {};
  const toggle = {dataset: {showLabel: 'Show menu', hideLabel: 'Hide menu'}, attrs: {},
    querySelector() {return label;},
    setAttribute(key, value) {this.attrs[key] = value;}, focus() {this.focused = true;},
    addEventListener(event, handler) {handlers[event] = handler;}};
  const document = {querySelector: () => null,
    getElementById(id) {return {commandDock: dock, dockToggle: toggle}[id] || null;},
    addEventListener(event, handler) {listeners[event] = handler;}};
  const window = {localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)}};
  vm.runInNewContext(source, {document, window});
  return {dock, toggle, label, storage, handlers, listeners};
}

test('dock button hides navigation and saves the preference across pages', () => {
  const fixture = dockFixture();
  fixture.handlers.click();
  assert.equal(fixture.dock.hidden, true);
  assert.equal(fixture.toggle.attrs['aria-expanded'], 'false');
  assert.equal(fixture.toggle.attrs['aria-label'], 'Show menu');
  assert.equal(dockFixture(fixture.storage.get('harness.navigation.hidden')).dock.hidden, true);
  fixture.handlers.click();
  assert.equal(fixture.dock.hidden, false);
});

test('Windows and macOS shortcuts toggle the dock and restore visible focus', () => {
  for (const modifier of ['ctrlKey', 'metaKey']) {
    const fixture = dockFixture('true');
    let prevented = false;
    fixture.listeners.keydown({[modifier]: true, shiftKey: true, key: 'M', preventDefault() {prevented = true;}});
    assert.equal(prevented, true);
    assert.equal(fixture.dock.hidden, false);
    assert.equal(fixture.toggle.focused, true);
  }
});

test('capture polling opens its execution without submitting the task again', async () => {
  let destination, calls = 0;
  const progress = {dataset: {submissionStatus: '/sessions/task/status', status: 'queued'}, querySelector: () => ({})};
  const document = {getElementById: () => null, querySelector: selector => selector === '[data-submission-status]' ? progress : null};
  const window = {location: {href: 'http://localhost:5088/?submission=task', origin: 'http://localhost:5088', replace(value) {destination = value;}}};
  const fetch = async (url, options) => {
    calls++;
    assert.equal(url, '/sessions/task/status');
    assert.equal(options.method, undefined);
    return {ok: true, json: async () => ({destination: '/remediation/1327'})};
  };
  vm.runInNewContext(source, {document, window, fetch, URL});
  await new Promise(setImmediate);
  assert.equal(destination, 'http://localhost:5088/remediation/1327');
  assert.equal(calls, 1);
});

test('capture failure stops the activity state without requiring the launch form', async () => {
  const attributes={}, message={textContent:''};
  const progress={dataset:{submissionStatus:'/sessions/task/status',status:'queued'},
    querySelector:()=>message,querySelectorAll:()=>[],setAttribute(key,value){attributes[key]=value;}};
  const document={getElementById:()=>null,querySelector:selector=>selector==='[data-submission-status]'?progress:null};
  let timers=0;
  const window={location:{href:'http://localhost/remediation/preparing/task',origin:'http://localhost'}};
  vm.runInNewContext(source,{document,window,URL,setTimeout(){timers++;},
    fetch:async()=>({ok:true,json:async()=>({status:'failed',phase:'capturing',message:'Capture failed'})})});
  await new Promise(setImmediate);
  assert.equal(progress.dataset.status,'failed');
  assert.equal(attributes['aria-busy'],'false');
  assert.equal(attributes.role,'alert');
  assert.equal(message.textContent,'Capture failed');
  assert.equal(timers,0);
});

test('temporary status failure keeps the task and schedules only a GET retry', async () => {
  const message={textContent:''};
  const progress={dataset:{submissionStatus:'/sessions/task/status',status:'queued',connectionMessage:'Reconnecting'},querySelector:()=>message};
  const document={getElementById:()=>null,querySelector:selector=>selector==='[data-submission-status]'?progress:null};
  let retries=0;
  vm.runInNewContext(source,{document,window:{AbortSignal:undefined},URL,setTimeout(callback,delay){assert.equal(delay,5000);retries++;},
    fetch:async(url,options)=>{assert.equal(options.method,undefined);throw new Error('Disconnected');}});
  await new Promise(setImmediate);
  assert.equal(message.textContent,'Reconnecting');
  assert.equal(retries,1);
});
