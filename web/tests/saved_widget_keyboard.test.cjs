const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('Escape closes the focused submenu before its mobile navigation container', () => {
  const handlers = {};
  const document = {activeElement: null};
  const element = () => ({
    open: true, children: new Set(),
    classList: {
      contains() {return this.owner.open;},
      toggle(name, value) {this.owner.open = value;}
    },
    setAttribute() {}, addEventListener() {},
    contains(child) {return this.children.has(child);},
    focus() {document.activeElement = this;}
  });
  const dropdown = element(), mobile = element(), dropdownTrigger = element(), mobileTrigger = element(), link = element();
  for (const item of [dropdown, mobile, dropdownTrigger, mobileTrigger, link]) item.classList.owner = item;
  dropdown.children.add(link);
  for (const item of [dropdown, dropdownTrigger, link]) mobile.children.add(item);
  const paths = [dropdownTrigger, dropdown, mobileTrigger, mobile].map((item, index) =>
    ['html > body:nth-of-type(1) > div:nth-of-type(' + (index + 1) + ')', item]);
  const state = {widgets: [{kind: 'dropdown', trigger: paths[0][0], panel: paths[1][0]},
                           {kind: 'collapse', trigger: paths[2][0], panel: paths[3][0]}]};
  document.querySelector = () => ({textContent: JSON.stringify(state)});
  document.querySelectorAll = selector => paths.filter(([key]) => key === selector).map(([, value]) => value);
  document.addEventListener = (name, callback) => {handlers[name] = callback;};
  document.activeElement = link;
  const source = fs.readFileSync(path.join(__dirname, '../app/static/js/saved_widgets.js'), 'utf8');
  vm.runInNewContext(source, {document});
  handlers.keydown({key: 'Escape', preventDefault() {}});
  assert.equal(dropdown.open, false);
  assert.equal(mobile.open, true);
  assert.equal(document.activeElement, dropdownTrigger);
  handlers.keydown({key: 'Escape', preventDefault() {}});
  assert.equal(mobile.open, false);
  assert.equal(document.activeElement, mobileTrigger);
});
