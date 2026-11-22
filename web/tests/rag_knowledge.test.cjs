const {test} = require('node:test');
const assert = require('node:assert/strict');
const {init} = require('../app/static/js/rag_knowledge.js');
const response = data => ({ok:true,json:async()=>data});
const state = (count=396, job={}, active_runs=0) => ({corpus:{reachable:true,count,official:374,complementary:22,synchronized_at:null},job,active_runs});
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(fetch, confirm=async()=>true) {
  const nodes={}, timers=new Map(), calls=[], observed=[]; let sequence=0;
  for (const id of ['ragSynchronize','ragCorpusStatus','ragOfficialCount','ragComplementaryCount',
    'ragSyncDate','ragSynchronizeLabel','ragBlockedReason','ragSyncProgress','ragSyncMessage']) {
    nodes[id]={textContent:'',hidden:false,disabled:true,attrs:{},events:{},style:{},
      setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this.events[k]=fn}};
  }
  nodes.bar={style:{}};nodes.progress=nodes.ragSyncProgress;
  nodes.progress.querySelector=s=>s==='[role="progressbar"]'?nodes.progress:nodes.bar;
  const panel={dataset:{statusUrl:'/status',syncUrl:'/sync',labels:JSON.stringify({initialize:'Initialize',update:'Update',
    available:'Available',empty:'Empty',unavailable:'Unavailable',unknown:'Not recorded',blocked:'Wait',
    confirm:'Confirm update',loadError:'Load error',queued:'Queued',index:'Indexing',completed:'Completed',
    interrupted:'Interrupted',syncError:'Failed; old corpus preserved'})},querySelector:s=>nodes[s.slice(1)]};
  const control=init(panel,{fetch:async(...args)=>{calls.push(args);return fetch(...args)},confirm,
    observeCorpus:version=>observed.push(version),
    setTimeout:(fn,ms)=>{const id=++sequence;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)});
  return {nodes,calls,timers,observed,control,click:()=>nodes.ragSynchronize.events.click(),
    runTimer(ms){const item=[...timers].find(([,v])=>v.ms===ms);assert.ok(item);timers.delete(item[0]);return item[1].fn()}};
}
test('opening only reads status; existing counts and unknown date are explicit',async()=>{
  const f=fixture(async()=>response(state()));await tick();
  assert.equal(f.calls.length,1);assert.equal(f.calls[0][0],'/status');
  assert.equal(f.nodes.ragOfficialCount.textContent,'374');
  assert.equal(f.nodes.ragComplementaryCount.textContent,'22');
  assert.equal(f.nodes.ragSyncDate.textContent,'Not recorded');
  assert.equal(f.nodes.ragSynchronizeLabel.textContent,'Update');assert.equal(f.nodes.ragSynchronize.disabled,false);
  assert.equal(f.nodes.ragSyncProgress.hidden,true);f.control.dispose();assert.equal(f.timers.size,0);
});
test('verified idle corpus is observed automatically, not during indexing or outages',async()=>{
  const f=fixture(async()=>response(state()));await tick();
  const data=state();data.corpus.synchronized_at='new-version';
  f.control.render({...data,job:{status:'running'}});assert.deepEqual(f.observed,[]);
  f.control.render({...data,corpus:{...data.corpus,reachable:false}});assert.deepEqual(f.observed,[]);
  f.control.render({...data,job:{status:'completed'}});assert.deepEqual(f.observed,['new-version']);
  assert.equal(f.calls.length,1);f.control.dispose();
  f.control.render(data);assert.equal(f.observed.length,1);
});
test('cancelled update makes no POST or implicit retry',async()=>{
  let confirmations=0;const f=fixture(async()=>response(state()),async()=>{++confirmations;return false});
  await tick();await f.click();assert.equal(confirmations,1);assert.equal(f.calls.length,1);f.control.dispose();
});
test('update requires confirmation, disables repeat clicks and displays worker progress',async()=>{
  let finish;const f=fixture(async(url)=>url==='/status'?response(state()):new Promise(resolve=>{finish=resolve}));
  await tick();const action=f.click();await tick();await f.click();
  assert.equal(f.calls.length,2);assert.deepEqual(JSON.parse(f.calls[1][1].body),{mode:'update',confirmed:true});
  finish(response({job:{status:'queued',phase:'queued',percent:0}}));await action;
  assert.equal(f.nodes.ragSyncProgress.hidden,false);assert.equal(f.nodes.ragSyncMessage.textContent,'Queued');
  f.control.render(state(396,{status:'running',phase:'index',percent:60}));
  assert.equal(f.nodes.bar.style.width,'60%');assert.equal(f.nodes.progress.attrs['aria-valuenow'],60);
  assert.equal(f.nodes.ragSynchronize.disabled,true);f.control.dispose();
});
test('initialization is explicit and requires no update confirmation',async()=>{
  let confirmations=0;const f=fixture(async(url)=>response(url==='/status'?state(0):{job:{status:'queued'}}),async()=>{++confirmations;return true});
  await tick();await f.click();assert.equal(confirmations,0);
  assert.deepEqual(JSON.parse(f.calls[1][1].body),{mode:'initialize',confirmed:false});f.control.dispose();
});
test('active runs or unreachable service disable maintenance',async()=>{
  const f=fixture(async()=>response(state(396,{},1)));await tick();await f.click();
  assert.equal(f.calls.length,1);assert.equal(f.nodes.ragBlockedReason.textContent,'Wait');
  const data=state();data.corpus.reachable=false;f.control.render(data);
  assert.equal(f.nodes.ragSynchronize.disabled,true);assert.equal(f.nodes.ragCorpusStatus.textContent,'Unavailable');f.control.dispose();
});
test('late GET cannot undo a queued explicit request',async()=>{
  let finish;let gets=0;const f=fixture(async(url)=>url==='/sync'?response({job:{status:'queued',phase:'queued'}}):
    ++gets===1?response(state()):new Promise(resolve=>{finish=resolve}));
  await tick();const old=f.control.load();await f.click();finish(response(state()));await old;
  assert.equal(f.nodes.ragSyncMessage.textContent,'Queued');assert.equal(f.nodes.ragSynchronize.disabled,true);f.control.dispose();
});
test('failure and interrupted states distinguish errors from successful sync',async()=>{
  const f=fixture(async()=>response(state()));await tick();
  f.control.render(state(396,{status:'failed',phase:'failed',error:'interrupted'}));
  assert.equal(f.nodes.ragSyncMessage.textContent,'Interrupted');
  f.control.render(state(396,{status:'failed',phase:'failed',error:'offline'}));
  assert.equal(f.nodes.ragSyncMessage.textContent,'Failed; old corpus preserved');f.control.dispose();
});
test('unresponsive status times out without starting synchronization',async()=>{
  const f=fixture((_,options)=>new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Error('timeout')))));
  f.runTimer(15000);await tick();assert.equal(f.nodes.ragSyncMessage.textContent,'Load error');
  assert.equal(f.nodes.ragSynchronize.disabled,true);assert.equal(f.calls.length,1);f.control.dispose();
});
test('dispose prevents late POST results or polling',async()=>{
  let finish;const f=fixture(async url=>url==='/status'?response(state()):new Promise(resolve=>{finish=resolve}));
  await tick();const action=f.click();await tick();f.control.dispose();finish(response({job:{status:'queued',phase:'queued'}}));await action;
  assert.equal(f.nodes.ragSyncMessage.textContent,'');assert.equal(f.timers.size,0);
});
