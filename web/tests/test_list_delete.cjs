const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/static/js/list_delete.js'), 'utf8');

async function scenario({accepted = true, blocked = false, networkError = false} = {}) {
    const result = {alerts: [], removed: false, rowRemoved:false, summaryUpdated: false, requests: 0, events:[]};
    const button = {disabled: false, setAttribute() {}, removeAttribute() {}};
    const scroll = {scrollLeft: 42};
    const table = {closest: () => scroll, querySelector: () => ({}), dispatchEvent:event=>result.events.push(event.type)};
    const row = {closest: () => table, remove: () => {result.rowRemoved = true;}};
    const group = {remove:()=>{result.removed=true;}};
    const form = {action: 'http://localhost/remediation/42/delete', dataset: {
        confirm: 'Delete?', confirmLabel: 'Delete', deleteError: 'Refresh before retrying',
    }, querySelector: () => button, closest: selector => selector === '[data-history-entry]' ? group : row};
    const message = {textContent: blocked ? 'Used by a comparison' : 'Deleted',
        classList: {contains: name => !blocked && name === 'alert-success'}};
    const main = {querySelectorAll: selector => selector.includes('.alert') ? [message] :
        (blocked ? [{getAttribute: () => '/remediation/42/delete'}] : []),
        querySelector: () => ({})};
    const context = {
        URL, CustomEvent: class {constructor(type){this.type=type;}}, FormData: class {}, DOMParser: class {parseFromString() {return {querySelector: () => main};}},
        setTimeout() {},
        fetch: async () => {result.requests++; if (networkError) throw new Error(); return {ok: true, text: async () => ''};},
        document: {
            querySelector: () => ({replaceWith: () => {result.summaryUpdated = true;}}),
            getElementById: () => null,
            createElement: () => ({style: {}, setAttribute() {}, remove() {}}),
            body: {append() {}},
        },
        window: {scrollY: 720, scrollX: 0, warpConfirm: async () => accepted,
            warpAlert: async text => result.alerts.push(text),
            scrollTo: (x, y) => {result.position = [x, y];}},
    };
    vm.runInNewContext(source, context);
    await context.window.warpDeleteListItem(form);
    assert.equal(button.disabled, false);
    assert.equal(scroll.scrollLeft, 42);
    return result;
}
(async () => {
    const success = await scenario();
    assert.equal(success.removed, true);
    assert.equal(success.rowRemoved, false);
    assert.equal(success.summaryUpdated, true);
    assert.deepEqual(success.position, [0, 720]);
    assert.deepEqual(success.events, ['history:changed']);
    const blocked = await scenario({blocked: true});
    assert.equal(blocked.removed, false);
    assert.deepEqual(blocked.alerts, ['Used by a comparison']);
    assert.equal(blocked.summaryUpdated, false);
    const failed = await scenario({networkError: true});
    assert.equal(failed.removed, false);
    assert.equal(failed.requests, 1);
    assert.deepEqual(failed.alerts, ['Refresh before retrying']);
    const cancelled = await scenario({accepted: false});
    assert.equal(cancelled.requests, 0);
    console.log('List deletion: success, blocked, connection failure and cancellation passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
