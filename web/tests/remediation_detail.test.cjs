const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../app/static/js/remediation_detail.js'), 'utf8');

function fixture(status = 'running', pushed=false, nextRevision=2) {
  const state = {timers: [], fetches: [], hidden: false, selection: '', failed: false, scroll: null, flowAnimations: [], listeners:{}};
  const detail = (count, open) => ({dataset:{reportPanel:'activity-log'}, open,
    closest:()=>null, querySelector:()=>({textContent:`Activity ${count} events`, focus(){}})});
  const node = (status, count) => ({dataset:{runStatus:status,liveEventsUrl:'/remediation/7/live-events'}, detail:detail(count,false),
    querySelectorAll(selector){return selector==='details[open]' ? (this.detail.open?[this.detail]:[]) : selector==='details'?[this.detail]:[];},
    querySelector:selector=>selector==='[data-flow-revision]'?{dataset:{flowRevision:String(count)},classList:{add:value=>state.flowAnimations.push(value)}}:null, contains:()=>false, replaceWith(next){state.root=next;}});
  state.root=node(status,1); state.root.detail.open=true;
  const document={getElementById:()=>state.root, querySelector:()=>null, get hidden(){return state.hidden;},
    getSelection:()=>({toString:()=>state.selection}), activeElement:null,addEventListener(name,callback){state.listeners[name]=callback;}};
  const window={location:{href:'http://localhost/remediation/7'},scrollY:300,
    scrollTo:value=>{state.scroll=value.top;},addEventListener(){}};
  if(pushed)window.EventSource=class{constructor(url){state.stream=this;this.url=url;}addEventListener(name,fn){this[name]=fn;}close(){state.streamClosed=true;}};
  class DOMParser {parseFromString(){return {getElementById:()=>node('accepted',nextRevision)};}}
  const fetch=async (url, options)=>{
    state.fetches.push({url,options}); if(state.failed) throw Error('offline');
    return {ok:true,text:async()=>'actual refreshed report'};
  };
  class FormData {constructor(form){this.form=form;}}
  vm.runInNewContext(code,{document,window,fetch,URL,DOMParser,AbortController,FormData,
    setTimeout:(fn,ms)=>{if(ms===4000)state.timers.push(fn);return 1;},clearTimeout(){}});
  return state;
}

function stopForm(state) {
  const button={disabled:false,textContent:'Stop',dataset:{stopLabel:'Stop',stoppingLabel:'Stopping…'}};
  const message={hidden:true,dataset:{error:'Could not request a stop.'}};
  const form={action:'/remediation/7/stop',querySelector:selector=>selector==='button'?button:message};
  state.root.contains=node=>node===form;
  return {button,message,form,event:{target:{closest:()=>form},preventDefault(){}}};
}

test('stop sends one scoped request and follows it with a read-only report refresh', async()=>{
  const state=fixture();
  const control=stopForm(state);
  await state.listeners.submit(control.event);
  assert.equal(control.button.disabled,true);
  assert.equal(control.button.textContent,'Stopping…');
  assert.equal(state.fetches[0].url,'/remediation/7/stop');
  assert.equal(state.fetches[0].options.method,'POST');
  assert.equal(state.fetches[0].options.body.form,control.form);
  assert.equal(state.fetches[1].options.method,undefined);
  await state.listeners.submit(control.event);
  assert.equal(state.fetches.filter(item=>item.options.method==='POST').length,1);
});

test('a failed stop request remains visible and can be retried',async()=>{
  const state=fixture();state.failed=true;
  const control=stopForm(state);
  await state.listeners.submit(control.event);
  assert.equal(control.button.disabled,false);
  assert.equal(control.button.textContent,'Stop');
  assert.equal(control.message.hidden,false);
  assert.equal(control.message.textContent,'Could not request a stop.');
});
test('live report preserves an open activity panel as event counts change, and stops on completion', async()=>{
  const s=fixture(); await s.timers.shift()();
  assert.equal(s.root.dataset.runStatus,'accepted'); assert.equal(s.root.detail.open,true);
  assert.equal(s.scroll,300); assert.equal(s.timers.length,0);
  assert.equal(s.fetches[0].url.searchParams.get('live'),'1');
  assert.equal(s.fetches[0].options.cache,'no-store');
});
test('failed requests keep the old report and retry',async()=>{
  const s=fixture(); s.failed=true; const original=s.root;
  await s.timers.shift()(); assert.equal(s.root,original); assert.equal(s.timers.length,1);
});
test('hidden and selected text defer read-only requests',async()=>{
  const s=fixture(); s.hidden=true; await s.timers.shift()();
  s.hidden=false; s.selection='copied prompt'; await s.timers.shift()();
  assert.equal(s.fetches.length,0); assert.equal(s.timers.length,1);
});
test('terminal reports do not poll',()=>assert.equal(fixture('accepted').timers.length,0));

test('recorded server events refresh immediately without four-second polling',async()=>{
 const s=fixture('running',true);
 assert.equal(s.timers.length,0);
 assert.equal(s.stream.url,'/remediation/7/live-events');
 await s.stream.activity();
 // The event listener schedules the async refresh directly.
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(s.fetches.length,1);
 assert.equal(s.root.dataset.runStatus,'accepted');
 assert.equal(s.streamClosed,true);
 assert.equal(s.timers.length,0);
});

test('transfer packets animate a new recorded revision, not an unchanged snapshot',async()=>{
 const changed=fixture();await changed.timers.shift()();
 assert.deepEqual(changed.flowAnimations,['is-new-activity']);
 const unchanged=fixture('running',false,1);await unchanged.timers.shift()();
 assert.deepEqual(unchanged.flowAnimations,[]);
});


test('source and candidate previews retain equal width near either edge and on keyboard focus', () => {
  const items = [];
  const window = {innerWidth: 1400, innerHeight: 900, addEventListener() {}};
  for (const right of [700, 1380]) {
    const item = {events: {}, properties: {}};
    item.preview = {style: {setProperty: (key, value) => {item.properties[key] = value;}},
      getBoundingClientRect: () => ({height: 420})};
    item.link = {querySelector: () => item.preview,
      getBoundingClientRect: () => ({right, top: 300}),
      addEventListener: (name, callback) => {item.events[name] = callback;}};
    items.push(item);
  }
  const root = {dataset: {runStatus: 'accepted'}, querySelectorAll: () => items.map(item => item.link)};
  const document = {getElementById: () => root, addEventListener() {}};
  vm.runInNewContext(code, {document, window,
    setTimeout() {throw Error('A closed report must not poll');}});
  items[0].events.pointerenter({clientX: 680, clientY: 500});
  items[1].events.pointerenter({clientX: 1300, clientY: 800});
  for (const item of items) {
    assert.equal(item.preview.style.width, '640px');
    assert.ok(parseFloat(item.properties['--preview-left']) >= 16);
    assert.ok(parseFloat(item.properties['--preview-left']) + 640 <= 1400 - 16);
    assert.ok(parseFloat(item.properties['--preview-top']) + 420 <= 900 - 16);
    item.events.focus({});
    assert.equal(item.preview.style.width, '640px');
  }
  window.innerWidth = 320;
  items[1].events.focus({});
  assert.equal(items[1].preview.style.width, '288px');
  assert.equal(items[1].properties['--preview-left'], '16px');
});
