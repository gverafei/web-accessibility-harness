const test = require('node:test');
const assert = require('node:assert/strict');
const {init} = require('../app/static/js/history_selection.js');

function fixture(serverPaged=false) {
  const target = value => Object.assign(value, {
    listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn; },
    emit(name, event = {}) { this.listeners[name]?.(event); }
  });
  const rows = [false, false, true].map((disabled,index) => {
    const entry = {hidden: false, dataset: {}};
    const input = {value:String(index+1), disabled, checked: false, entry, closest: () => entry};
    entry.querySelector = () => input;
    return input;
  });
  const all = target({checked: false}), button = {}, count = {};
  const table = target({querySelectorAll: () => rows, closest:()=>serverPaged?{}:null});
  const nodes = {'[data-history-select-all]': all, '[data-history-export]': button,
    '[data-history-selection-count]': count};
  const form = target({dataset: {historySelection: '.history'}, querySelector: selector => nodes[selector]});
  const env = {document: {querySelectorAll: () => [form], querySelector: () => table}};
  init(env);
  return {rows, all, button, count, table, form, env};
}

test('export is disabled initially; selecting a record exposes the count', () => {
  const f = fixture();
  assert.equal(f.button.disabled, true);
  assert.equal(f.count.hidden, true);
  f.rows[0].checked = true; f.table.emit('change');
  assert.equal(f.button.disabled, false);
  assert.equal(f.count.textContent, '(1)');
  assert.equal(f.all.indeterminate, true);
  assert.equal(f.rows[0].entry.dataset.historySelected, 'true');
});

test('select all affects only visible terminal rows, preserving hidden selections', () => {
  const f = fixture();
  f.rows[0].checked = true; f.rows[0].entry.hidden = true;
  f.table.emit('history:filtered');
  f.all.checked = true; f.all.emit('change');
  assert.deepEqual(f.rows.map(row => row.checked), [true, true, false]);
  assert.equal(f.count.textContent, '(2)');
  assert.equal(f.all.checked, true);
  assert.equal(f.rows[1].entry.dataset.historySelected, 'true');
  f.all.checked = false; f.all.emit('change');
  assert.deepEqual(f.rows.map(row => row.checked), [true, false, false]);
  assert.equal(f.count.textContent, '(1)');
  assert.equal(f.rows[1].entry.dataset.historySelected, 'false');
  f.rows[1].entry.hidden = true; f.table.emit('history:filtered');
  assert.equal(f.all.disabled, true);
  assert.equal(f.button.disabled, false);
});

test('filtering and view changes do not clear selection; deleting it updates the count', () => {
  const f = fixture();
  f.rows[0].checked = true;
  f.rows[0].entry.hidden = true; f.table.emit('history:filtered');
  f.table.emit('history:changed');
  assert.equal(f.count.textContent, '(1)');
  f.rows[0].entry.hidden = false; f.table.emit('history:filtered');
  assert.equal(f.rows[0].checked, true);
  f.rows.splice(0, 1); f.table.emit('history:changed');
  assert.equal(f.button.disabled, true);
  assert.equal(f.count.hidden, true);
});

test('live completion makes a row eligible without selecting it', () => {
  const f = fixture();
  f.rows[0].entry.hidden = f.rows[1].entry.hidden = true;
  f.table.emit('history:filtered');
  assert.equal(f.all.disabled, true);
  f.rows[2].disabled = false; f.table.emit('history:filtered');
  assert.equal(f.all.disabled, false);
  assert.equal(f.button.disabled, true);
  f.all.checked = true; f.all.emit('change');
  assert.equal(f.rows[2].checked, true);
  assert.equal(f.count.textContent, '(1)');
});

test('submission requires selection, including selections hidden by filtering', () => {
  const f = fixture(); let prevented = false;
  const event = {preventDefault() { prevented = true; }};
  f.form.emit('submit', event); assert.equal(prevented, true);
  prevented = false;
  f.rows[0].checked = true; f.rows[0].entry.hidden = true;
  f.form.emit('submit', event); assert.equal(prevented, false);
});

function rowClick(f, row = f.rows[0], interactive = false, extra = {}) {
  f.table.emit('click', {button: 0,
    target: {closest: selector => selector === '[data-history-entry]' ? row.entry : interactive ? {} : null}, ...extra});
}

test('clicking record body or footer background toggles checkbox and entire record highlight', () => {
  const f = fixture();
  rowClick(f);
  assert.equal(f.rows[0].checked, true);
  assert.equal(f.rows[0].entry.dataset.historySelected, 'true');
  assert.equal(f.count.textContent, '(1)');
  rowClick(f);
  assert.equal(f.rows[0].checked, false);
  assert.equal(f.rows[0].entry.dataset.historySelected, 'false');
  assert.equal(f.button.disabled, true);
});

test('checkboxes, links, buttons, text selection and right clicks do not toggle the record twice', () => {
  const f = fixture();
  rowClick(f, f.rows[0], true);
  rowClick(f, f.rows[0], false, {button: 2});
  rowClick(f, f.rows[0], false, {defaultPrevented: true});
  f.env.getSelection = () => 'text being copied';
  rowClick(f);
  assert.equal(f.rows[0].checked, false);
  // Native keyboard/click checkbox change still updates the highlight.
  f.rows[0].checked = true; f.table.emit('change');
  assert.equal(f.rows[0].entry.dataset.historySelected, 'true');
});

test('active or hidden records ignore clicks; live completion makes them clickable', () => {
  const f = fixture();
  rowClick(f, f.rows[2]);
  assert.equal(f.rows[2].checked, false);
  assert.equal(f.rows[2].entry.dataset.historySelectable, 'false');
  f.rows[0].entry.hidden = true; rowClick(f);
  assert.equal(f.rows[0].checked, false);
  f.rows[2].disabled = false; f.table.emit('history:filtered');
  rowClick(f, f.rows[2]);
  assert.equal(f.rows[2].entry.dataset.historySelected, 'true');
});


test('server paging keeps selections when records leave and reenter the visible page', () => {
 const f=fixture(true);
 f.rows[0].checked=true;f.table.emit('change');
 const selected=f.rows.shift();f.table.emit('history:changed');
 assert.equal(f.count.textContent,'(1)');
 f.rows.unshift({...selected,checked:false});f.table.emit('history:changed');
 assert.equal(f.rows[0].checked,true);
 f.rows[0].checked=false;f.table.emit('change');
 assert.equal(f.button.disabled,true);
});
