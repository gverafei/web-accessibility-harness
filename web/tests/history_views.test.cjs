const test = require('node:test');
const assert = require('node:assert/strict');
const {init, restore} = require('../app/static/js/history_views.js');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture(saved, blocked=false) {
  const views = [{dataset:{}}, {dataset:{}}];
  const buttons = views.map(() => ['table','cards'].map(mode => ({dataset:{historyMode:mode},
    setAttribute(name,value){this[name]=value;},closest(){return this;}})));
  const controls = views.map((_,i) => ({dataset:{historyViewControls:String(i)},
    querySelectorAll:()=>buttons[i],contains:b=>buttons[i].includes(b),
    addEventListener(_,fn){this.click=fn;}}));
  const storage = {getItem(){if(blocked)throw Error();return saved;},
    setItem(key,value){if(blocked)throw Error();this.saved=[key,value];}};
  const documentElement = {dataset:{}};
  init({document:{documentElement,querySelectorAll:()=>controls,getElementById:id=>views[id]},localStorage:storage});
  return {views,buttons,controls,storage,documentElement};
}
test('table default and card preference are shared between histories',()=>{
  const s=fixture(); assert.deepEqual(s.views.map(v=>v.dataset.historyView),['table','table']);
  s.controls[0].click({target:s.buttons[0][1]});
  assert.deepEqual(s.views.map(v=>v.dataset.historyView),['cards','cards']);
  assert.equal(s.documentElement.dataset.historyView, 'cards');
  assert.equal(s.buttons[1][1]['aria-pressed'],'true');
  assert.equal(s.buttons[1][0]['aria-pressed'],'false');
  assert.deepEqual(s.storage.saved,['history-list-view','cards']);
  s.controls[1].click({target:s.buttons[1][0]});
  assert.equal(s.views[0].dataset.historyView,'table');
  assert.equal(s.documentElement.dataset.historyView, 'table');
});
test('restores cards, ignores unknown values and works without browser storage',()=>{
  assert.equal(fixture('cards').views[0].dataset.historyView,'cards');
  assert.equal(fixture('garbage').views[0].dataset.historyView,'table');
  const s=fixture(null,true); s.controls[0].click({target:s.buttons[0][1]});
  assert.equal(s.views[0].dataset.historyView,'cards');
});
test('only a view control can change the mode',()=>{
  const s=fixture(); s.controls[0].click({target:{closest:()=>null}});
  s.controls[0].click({target:{closest:()=>({dataset:{historyMode:'cards'}})}});
  assert.equal(s.views[0].dataset.historyView,'table');
});

test('head restoration does not need controls or a parsed body',()=>{
  for (const saved of ['cards', 'table', 'invalid', null]) {
    const env = {document:{documentElement:{dataset:{}}},
      localStorage:{getItem:()=>saved}};
    assert.equal(restore(env), saved === 'cards' ? 'cards' : 'table');
    assert.equal(env.document.documentElement.dataset.historyView,
      saved === 'cards' ? 'cards' : 'table');
  }
  const env = {document:{documentElement:{dataset:{}}},
    get localStorage(){throw Error('denied');}};
  assert.equal(restore(env), 'table');
});

test('browser bootstrap restores before paint and binds controls after DOM ready',()=>{
  const source = fs.readFileSync(path.join(__dirname, '../app/static/js/history_views.js'), 'utf8');
  let ready, scans = 0;
  const documentElement = {dataset:{}};
  const window = {localStorage:{getItem:()=> 'cards'}, document:{documentElement,
    readyState:'loading', querySelectorAll(){scans++; return [];},
    addEventListener(name, callback, options){
      assert.equal(name, 'DOMContentLoaded'); assert.equal(options.once, true); ready = callback;
    }}};
  vm.runInNewContext(source, {window});
  assert.equal(documentElement.dataset.historyView, 'cards');
  assert.equal(scans, 0, 'head bootstrap never waits for or scans missing controls');
  ready();
  assert.equal(scans, 1);
});
