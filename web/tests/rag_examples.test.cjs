const {test} = require('node:test');
const assert = require('node:assert/strict');
const {init} = require('../app/static/js/rag_examples.js');

function fixture(fetch) {
    let count=0; const timers=new Map(), calls=[], history=[], scroll=[], events={};
    const nodes={message:{textContent:''},rows:{innerHTML:'original rows'},
        pager:{innerHTML:'original pager'},toolbar:{getBoundingClientRect:()=>({top:145})},
        size:{focus(){}},summary:{textContent:'old summary'},provenance:{innerHTML:'old provenance',open:true}};
    const form={action:'http://localhost/rag-act',events:{},values:{q:'image',source:'official',outcome:'failed',size:'5',collection:'snapshot'},
        querySelector(){return {get value(){return form.values.collection},set value(v){form.values.collection=v}}},
        addEventListener(k,fn){this.events[k]=fn}};
    const find=k=>({'form':form,'#ragBrowseMessage':nodes.message,'tbody':nodes.rows,
        '#ragExampleCounts':nodes.summary,'#ragCorpusProvenance':nodes.provenance,
        '.measurement-pagination':nodes.pager,'.report-pagination-toolbar':nodes.toolbar,'[name="size"]':nodes.size}[k]);
    const panel={dataset:{corpusVersion:'old-version',loading:'Loading',loadError:'Failed; previous results retained',changedError:'Reload corpus'},
        attrs:{},events:{},querySelector:find,setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this.events[k]=fn}};
    const env={document:{getElementById:()=>panel,activeElement:{getAttribute:()=>null,closest:()=>null}},
        location:{href:'http://localhost/rag-act',origin:'http://localhost'},
        FormData:class {constructor(){return Object.entries(form.values)}},
        DOMParser:class {parseFromString(html){return {getElementById:()=>html==='bad'?null:{
            dataset:{corpusVersion:html==='new-corpus'?'new-version':'old-version'},
            querySelector:key=>({innerHTML:html+key,textContent:html+key,value:html==='new-corpus'?'new-snapshot':'snapshot'})}}}},
        addEventListener:(k,fn)=>events[k]=fn,removeEventListener:k=>delete events[k],
        fetch:async(...args)=>{calls.push(args);return fetch(...args)},
        history:{replaceState:(_,__,url)=>history.push(url)},scrollBy:x=>scroll.push(x),requestAnimationFrame:fn=>fn(),
        setTimeout:(fn,ms)=>{const id=++count;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)};
    const control=init(env);
    return {panel,form,nodes,control,calls,history,scroll,timers,events,runTimer(ms){const item=[...timers].find(([,v])=>v.ms===ms);assert.ok(item);timers.delete(item[0]);return item[1].fn()}};
}
const response=html=>({ok:true,text:async()=>html});

test('initialization makes no call; successful paging updates only rows/pager without scrolling',async()=>{
    const f=fixture(async()=>response('page2'));
    assert.equal(f.calls.length,0);
    await f.control.load('/rag-act?collection=snapshot&page=2');
    assert.equal(f.nodes.rows.innerHTML,'page2tbody');
    assert.equal(f.nodes.pager.innerHTML,'page2.measurement-pagination');
    assert.equal(f.history[0],'/rag-act?collection=snapshot&page=2');
    assert.deepEqual(f.scroll,[]);
    assert.equal(f.panel.attrs['aria-busy'],'false');
});
test('select changes apply immediately and reset page, search debounces without submitting',async()=>{
    const f=fixture(async()=>response('filtered'));
    await f.panel.events.change({target:{matches:()=>true}});
    assert.match(f.calls[0][0],/source=official/);
    assert.match(f.calls[0][0],/page=1/);
    f.form.values.q='new'; f.panel.events.input({target:{name:'q'}});
    assert.equal(f.calls.length,1);
    await f.runTimer(250);
    assert.match(f.calls[1][0],/q=new/);
});
test('late responses and disposed requests cannot overwrite newer results',async()=>{
    const pending=[];const f=fixture(()=>new Promise(resolve=>pending.push(resolve)));
    const first=f.control.load('/rag-act?page=2');
    const second=f.control.load('/rag-act?page=3');
    assert.equal(f.calls[0][1].signal.aborted,true);
    pending[1](response('new')); await second;
    pending[0](response('old')); await first;
    assert.equal(f.nodes.rows.innerHTML,'newtbody');
    const third=f.control.load('/rag-act?page=4'); f.control.dispose();pending[2](response('late'));await third;
    assert.equal(f.nodes.rows.innerHTML,'newtbody');
});
test('HTTP/parse/network failures retain rows; stale snapshot recovery is bounded and GET-only',async()=>{
    for(const fetch of [async()=>({ok:false,status:503}),async()=>response('bad'),async()=>{throw Error('offline')}]) {
        const f=fixture(fetch);await f.control.load('/rag-act');
        assert.equal(f.nodes.rows.innerHTML,'original rows');
        assert.equal(f.nodes.message.textContent,f.panel.dataset.loadError);
        assert.equal(f.panel.attrs['aria-busy'],'false');
        assert.deepEqual(f.history,[]);
    }
    const f=fixture(async()=>({ok:false,status:409}));await f.control.load('/rag-act');
    assert.equal(f.nodes.message.textContent,'Reload corpus');
    assert.equal(f.calls.length,2);assert.ok(f.calls.every(([,options])=>!options.method));
    assert.equal(new URL(f.calls[1][0]).searchParams.has('collection'),false);
});
test('new corpus automatically refreshes all evidence together, preserving filters and position',async()=>{
    let finish;const f=fixture(()=>new Promise(resolve=>finish=resolve));
    f.events['rag-corpus-observed']({detail:{version:'old-version'}});assert.equal(f.calls.length,0);
    f.events['rag-corpus-observed']({detail:{version:'new-version'}});
    f.events['rag-corpus-observed']({detail:{version:'new-version'}});assert.equal(f.calls.length,1);
    const url=new URL(f.calls[0][0]);assert.equal(url.searchParams.has('collection'),false);
    assert.equal(url.searchParams.get('q'),'image');assert.equal(url.searchParams.get('page'),'1');
    finish(response('new-corpus'));await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.nodes.rows.innerHTML,'new-corpustbody');
    assert.equal(f.nodes.summary.textContent,'new-corpus#ragExampleCounts');
    assert.equal(f.nodes.provenance.innerHTML,'new-corpus#ragCorpusProvenance');assert.equal(f.nodes.provenance.open,true);
    assert.equal(f.form.values.collection,'new-snapshot');assert.equal(f.panel.dataset.corpusVersion,'new-version');
    assert.match(f.history[0],/collection=new-snapshot/);assert.deepEqual(f.scroll,[]);
    f.events['rag-corpus-observed']({detail:{version:'new-version'}});assert.equal(f.calls.length,1);
    f.control.dispose();assert.equal(f.events['rag-corpus-observed'],undefined);
});
test('failed automatic read retains old snapshot and retries on later status, never synchronizes',async()=>{
    let reads=0;const f=fixture(async()=>++reads===1?{ok:false,status:503}:response('new-corpus'));
    const event={detail:{version:'new-version'}};
    f.events['rag-corpus-observed'](event);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.nodes.rows.innerHTML,'original rows');assert.equal(f.form.values.collection,'snapshot');
    f.events['rag-corpus-observed'](event);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.form.values.collection,'new-snapshot');assert.equal(f.calls.length,2);
    assert.ok(f.calls.every(([url,options])=>new URL(url).pathname==='/rag-act'&&!options.method));
});
test('timeout aborts and foreign URLs are never loaded',async()=>{
    const f=fixture((_,options)=>new Promise((__,reject)=>options.signal.addEventListener('abort',()=>reject(Error('timeout')))));
    await f.control.load('https://outside.example/rag-act');await f.control.load('/configuration');
    assert.equal(f.calls.length,0);
    const pending=f.control.load('/rag-act'); f.runTimer(10000);await pending;
    assert.equal(f.nodes.rows.innerHTML,'original rows');
    assert.equal(f.panel.attrs['aria-busy'],'false');
});
test('paging intercepts ordinary clicks and uses current filters, but modifier clicks remain native',async()=>{
    const f=fixture(async()=>response('page'));
    const event={target:{closest:()=>({href:'http://localhost/rag-act?q=old&page=3'})},preventDefault(){this.prevented=true}};
    f.panel.events.click(event);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(event.prevented,true);assert.match(f.calls[0][0],/q=image/);assert.match(f.calls[0][0],/page=3/);
    event.metaKey=true; f.panel.events.click(event);assert.equal(f.calls.length,1);
});
