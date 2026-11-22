const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../app/static/js/remediation_history.js'), 'utf8');

function fixture(size=1) {
  const state = {rows:[], timers:[], calls:[], notice:{hidden:true}, input:{value:'example', addEventListener(_,fn){this.filter=fn;}}, count:{}, failed:false, hidden:false};
  function row(id, status) {
    const item = {dataset:{runId:String(id),runStatus:status}, textContent:`example ${id}`, hidden:false};
    const entry = {hidden:false, actions:status, row:item,
      replaceWith(next) {state.rows[state.rows.indexOf(item)]=next.row;}};
    item.closest = () => entry;
    return item;
  }
  state.rows=Array.from({length:size},(_, i)=>row(i+1,'running'));
  const document = {querySelector:()=>({querySelectorAll:()=>state.rows, addEventListener(){}}),
    getElementById:id=>({'remediationListFilter':state.input,'remediationFilterCount':state.count,'remediationLiveStatus':state.notice}[id]),
    get hidden(){return state.hidden;}};
  class DOMParser {parseFromString(html) {const ids=JSON.parse(html.slice(html.indexOf('['),html.lastIndexOf(']')+1)); return {querySelectorAll:()=>ids.map(id=>row(id,'completed_with_warnings'))};}}
  const window = {location:{href:'http://localhost/remediation/'},setTimeout:fn=>state.timers.push(fn),warpInteractionActive:()=>false};
  const fetch = async url => {state.calls.push(url); if(state.failed)throw new Error('offline'); return {ok:true,text:async()=>JSON.stringify(url.searchParams.get('live_ids').split(','))};};
  vm.runInNewContext(code,{document,window,fetch,URL,DOMParser});
  return state;
}

test('live rows update while filtered, preserve input and stop at terminal status',async()=>{
  const s=fixture(); await s.timers.shift()();
  assert.equal(s.calls.length,1); assert.equal(s.input.value,'example');
  assert.equal(s.rows[0].dataset.runStatus,'completed_with_warnings');
  assert.equal(s.rows[0].hidden,false); await s.timers.shift()();
  assert.equal(s.rows[0].closest().actions,'completed_with_warnings');
  assert.equal(s.calls.length,1); assert.equal(s.timers.length,0);
});
test('filter hides the complete record including action footer',()=>{
  const s=fixture(); s.input.value='not found';
  s.input.filter();
  assert.equal(s.rows[0].closest().hidden,true);
  assert.equal(s.count.textContent,'0 / 1');
  s.input.value='example'; s.input.filter();
  assert.equal(s.rows[0].closest().hidden,false);
});
test('requests are bounded and only identify active rows',async()=>{
  const s=fixture(55); s.rows[0].dataset.runStatus='accepted';
  await s.timers.shift()(); assert.equal(s.calls.length,2);
  assert.equal(s.calls[0].searchParams.get('live_ids').split(',').length,50);
  assert.equal(s.calls[1].searchParams.get('live_ids').split(',').length,4);
  assert.equal(s.calls[0].searchParams.get('live_ids').split(',').includes('1'),false);
});
test('network failure retains rows and retries',async()=>{
  const s=fixture(); s.failed=true; await s.timers.shift()();
  assert.equal(s.notice.hidden,false); assert.equal(s.rows[0].dataset.runStatus,'running');
  s.failed=false; await s.timers.shift()(); assert.equal(s.notice.hidden,true);
});
test('hidden tabs defer polling without losing the timer',async()=>{
  const s=fixture(); s.hidden=true; await s.timers.shift()();
  assert.equal(s.calls.length,0); assert.equal(s.timers.length,1);
  s.hidden=false; await s.timers.shift()(); assert.equal(s.calls.length,1);
});
