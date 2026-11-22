const {test} = require('node:test');
const assert = require('node:assert/strict');
const {init, escapeHtml} = require('../app/static/js/global_search.js');
function fixture(fetch) {
    const nodes = {}, timers = new Map(); let nextTimer = 0;
    for (const id of ['searchOverlay','globalSearch','globalSearchInput','searchDialogInput','searchSuggestions','backdrop']) {
        nodes[id] = {value:'', hidden:false, innerHTML:'', attrs:{}, events:{}, dataset:{},
            addEventListener(k,fn){this.events[k]=fn},setAttribute(k,v){this.attrs[k]=v},
            focus(){},select(){}};
    }
    const overlay = nodes.searchOverlay; overlay.hidden=true;
    overlay.dataset = {url:'/experiments/search-suggestions',loading:'Searching',empty:'No matches',error:'Unavailable'};
    overlay.querySelector = ()=>nodes.backdrop;
    nodes.globalSearch.action='/experiments';
    const navigation = [], calls = [], events = {};
    const env = {document:{getElementById:id=>nodes[id], addEventListener:(k,fn)=>{events[k]=fn}},
        AbortController, location:{assign:url=>navigation.push(url)},
        setTimeout:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id),
        fetch:async (...args)=>{calls.push(args);return fetch(...args)}};
    const control = init(env);
    return {nodes,overlay,navigation,calls,timers,events,control,
        runTimer(ms){const item=[...timers].find(([,v])=>v.ms===ms);assert.ok(item);timers.delete(item[0]);return item[1].fn()}};
}
const payload = title=>({experiments:[{id:131,title,status:'completed',date:'2026-09-24',href:'/experiments/131/loading'}],
    urls:[{experiment_id:131,url:'https://nike.com/',title,href:'/experiments/131/loading#url-results'}]});
const response = data=>({ok:true,json:async()=>data});
test('search renders loading links, encodes query and escapes stored text',async()=>{
    const f=fixture(async()=>response(payload('<script>bad</script>')));
    f.nodes.globalSearchInput.value='nike & co'; f.control.open(); await f.runTimer(160);
    assert.equal(f.calls[0][0],'/experiments/search-suggestions?q=nike%20%26%20co');
    assert.match(f.nodes.searchSuggestions.innerHTML,/href="\/experiments\/131\/loading#url-results"/);
    assert.match(f.nodes.searchSuggestions.innerHTML,/&lt;script&gt;/);
    assert.doesNotMatch(f.nodes.searchSuggestions.innerHTML,/<script>/);
    assert.equal(f.nodes.searchSuggestions.attrs['aria-busy'],'false');
    assert.equal(f.timers.size,0);
});
test('typing invalidates an old response before the next debounce expires',async()=>{
    const pending=[]; const f=fixture(()=>new Promise(resolve=>pending.push(resolve)));
    f.control.open(); const first=f.runTimer(160);
    f.nodes.searchDialogInput.value='new'; f.control.schedule();
    assert.equal(f.calls[0][1].signal.aborted,true);
    pending[0](response(payload('Old response'))); await first;
    assert.doesNotMatch(f.nodes.searchSuggestions.innerHTML,/Old response/);
    assert.equal(f.nodes.searchSuggestions.attrs['aria-busy'],'true');
    const second=f.runTimer(160); pending[1](response(payload('New response'))); await second;
    assert.match(f.nodes.searchSuggestions.innerHTML,/New response/);
});
test('closing cancels a pending request and prevents late content changes',async()=>{
    let resolve; const f=fixture(()=>new Promise(done=>{resolve=done}));
    f.control.open(); const request=f.runTimer(160); f.control.close();
    const html=f.nodes.searchSuggestions.innerHTML;
    resolve(response(payload('Late'))); await request;
    assert.equal(f.overlay.hidden,true);
    assert.equal(f.calls[0][1].signal.aborted,true);
    assert.equal(f.nodes.searchSuggestions.innerHTML,html);
});
test('HTTP, malformed JSON and network errors are visible and clear busy state',async()=>{
    for(const fetch of [async()=>({ok:false}),async()=>response({wrong:true}),async()=>{throw Error('offline')}]) {
        const f=fixture(fetch); f.control.open(); await f.runTimer(160);
        assert.match(f.nodes.searchSuggestions.innerHTML,/Unavailable/);
        assert.equal(f.nodes.searchSuggestions.attrs['aria-busy'],'false');
        assert.equal(f.timers.size,0);
    }
});
test('ten-second timeout stops an unresponsive search',async()=>{
    const f=fixture((_,options)=>new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Error('timeout')))));
    f.control.open(); const request=f.runTimer(160); f.runTimer(10000); await request;
    assert.match(f.nodes.searchSuggestions.innerHTML,/Unavailable/);
    assert.equal(f.nodes.searchSuggestions.attrs['aria-busy'],'false');
});
test('empty results and unsafe destinations never become actionable links',async()=>{
    const data=payload('Unsafe'); data.experiments[0].href='javascript:alert(1)';data.urls[0].href='https://outside.test/';
    const f=fixture(async()=>response(data)); f.control.open();await f.runTimer(160);
    assert.match(f.nodes.searchSuggestions.innerHTML,/No matches/);
    assert.doesNotMatch(f.nodes.searchSuggestions.innerHTML,/<a /);
    assert.equal(escapeHtml('"\'&<>'),'&quot;&#39;&amp;&lt;&gt;');
});
test('Enter preserves evaluation-list search and Escape closes the overlay',async()=>{
    const f=fixture(async()=>response({experiments:[],urls:[]}));f.control.open();
    f.nodes.searchDialogInput.value='imported'; let prevented=false;
    f.nodes.searchDialogInput.events.keydown({key:'Enter',preventDefault(){prevented=true}});
    assert.equal(prevented,true);assert.deepEqual(f.navigation,['/experiments?q=imported']);
    f.nodes.searchDialogInput.events.keydown({key:'Escape'});assert.equal(f.overlay.hidden,true);
    assert.equal(f.nodes.globalSearchInput.value,'imported');
});
