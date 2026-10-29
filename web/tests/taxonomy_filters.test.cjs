const test=require('node:test'),assert=require('node:assert/strict');
const {init}=require('../app/static/js/taxonomy_filters.js');
function fixture(fetch, path="/taxonomy", catalogRows){
 const timers=new Map();let timerId=0;
 const calls=[],history=[],scroll=[],events={},rows={innerHTML:'old rows',dispatchEvent(){}},pager={innerHTML:'old pager',querySelectorAll:()=>[]};
 const results={style:{},getBoundingClientRect:()=>({height:640})},message={textContent:''};
 const form={getBoundingClientRect:()=>({top:200}),action:'http://localhost'+path,values:{q:'label',category:'Semantic',size:'5'},addEventListener:(k,v)=>events['form:'+k]=v,querySelector:()=>({focus(){}}),contains:target=>target.insideForm===true};
 const panel={id:path==='/memory'?'memoryCatalogPanel':path==='/remediation/'?'remediationCatalogPanel':'taxonomyCatalogPanel',dataset:{loadError:'Could not update',catalogRows},querySelector:k=>({'form':form,'tbody':rows,'table':rows,'.measurement-pagination':pager,'.taxonomy-results':results,'#taxonomyBrowseMessage':message}[k]),addEventListener:(k,v)=>events[k]=v,setAttribute(){}};
 const env={document:{getElementById:id=>id===panel.id?panel:null,activeElement:{closest:()=>null}},location:{href:'http://localhost'+path,origin:'http://localhost'},FormData:class{constructor(){return Object.entries(form.values)}},DOMParser:class{parseFromString(html){return {getElementById:()=>html==='bad'?null:{querySelector:k=>({innerHTML:html+k})}}}},fetch:async(...a)=>{calls.push(a);return fetch(...a)},history:{replaceState:(_,__,url)=>history.push(url)},requestAnimationFrame:fn=>fn(),scrollBy(value){scroll.push(value);},setTimeout(fn,delay){timers.set(++timerId,{fn,delay});return timerId;},clearTimeout(id){timers.delete(id);}};
 return {control:init(env),timers,calls,history,scroll,form,events,rows,pager,results,message};
}
const response=html=>({ok:true,text:async()=>html});
test('paging updates rows only, preserves table height and removes navigation anchor',async()=>{
 const f=fixture(async()=>response('page2'));await f.control.load('/taxonomy?category=Semantic&size=5&page=2',true);
 assert.equal(f.rows.innerHTML,'page2tbody');assert.equal(f.results.style.minHeight,'640px');assert.deepEqual(f.history,['/taxonomy?category=Semantic&size=5&page=2']);
});
test('failed or malformed response retains visible rows and reports error',async()=>{
 for(const answer of [{ok:false},response('bad')]){const f=fixture(async()=>answer);await f.control.load('/taxonomy?page=2',true);assert.equal(f.rows.innerHTML,'old rows');assert.equal(f.message.textContent,'Could not update');}
});
test('late response cannot overwrite newer filters or disposed page',async()=>{
 const pending=[],f=fixture(()=>new Promise(resolve=>pending.push(resolve)));
 const first=f.control.load('/taxonomy?page=2'),second=f.control.load('/taxonomy?page=3');
 assert.equal(f.calls[0][1].signal.aborted,true);pending[1](response('new'));await second;pending[0](response('old'));await first;assert.equal(f.rows.innerHTML,'newtbody');
 const last=f.control.load('/taxonomy?page=4');f.control.dispose();pending[2](response('late'));await last;assert.equal(f.rows.innerHTML,'newtbody');
});
test('modified clicks remain native; normal paging is GET-only',async()=>{
 const f=fixture(async()=>response('next'));let prevented=false;
 const target={closest:()=>({href:'http://localhost/taxonomy?page=2'})};
 f.events.click({target,ctrlKey:true,preventDefault(){prevented=true;}});assert.equal(prevented,false);assert.equal(f.calls.length,0);
 f.events.click({target,preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(f.calls.length,1);assert.equal(f.calls[0][1].method,undefined);
});

test('browser anchoring drift is compensated after layout without smooth scrolling',async()=>{
 const f=fixture(async()=>response('short'));let reads=0;
 f.form.getBoundingClientRect=()=>({top:++reads===1?200:240});
 await f.control.load('/taxonomy?page=20',true);
 assert.deepEqual(f.scroll,[{top:40,behavior:'instant'}]);
});

test('typing debounces requests, invalidates old responses and cancels on disposal',async()=>{
 const pending=[],f=fixture(()=>new Promise(resolve=>pending.push(resolve)));
 const old=f.control.load('/taxonomy?page=2');
 f.form.values.q='new';f.events.input({target:{name:'q'}});
 assert.equal(f.calls[0][1].signal.aborted,true);
 f.form.values.q='newer';f.events.input({target:{name:'q'}});
 assert.equal([...f.timers.values()].filter(t=>t.delay===250).length,1);
 pending[0](response('stale'));await old;
 assert.equal(f.rows.innerHTML,'old rows');
 const next=[...f.timers.values()].find(t=>t.delay===250).fn();
 assert.equal(f.calls.length,2);assert.match(f.calls[1][0],/q=newer/);
 pending[1](response('fresh'));await next;
 assert.equal(f.rows.innerHTML,'freshtbody');
 f.events.input({target:{name:'q'}});f.control.dispose();
 assert.equal([...f.timers.values()].filter(t=>t.delay===250).length,0);
});

test('memory uses its endpoint and rejects unrelated catalogue URLs', async () => {
 const f = fixture(async () => response('memory'), '/memory');
 await f.control.load('/taxonomy?page=2');
 assert.equal(f.calls.length, 0);
 await f.control.load('/memory?outcome=improved&size=5&page=2', true);
 assert.equal(f.rows.innerHTML, 'memorytbody');
 assert.deepEqual(f.history, ['/memory?outcome=improved&size=5&page=2']);
});


test('remediation pages replace complete record groups and ignore export checkbox changes', async () => {
 const f=fixture(async()=>response('runs'),'/remediation/');
 await f.control.load('/remediation/?page=2',true);
 assert.equal(f.rows.innerHTML,'runstable');
 const previous=f.calls.length;
 f.events.change({target:{name:'run_ids'}});
 assert.equal(f.calls.length,previous);
 f.events.change({target:{name:'size',insideForm:true}});
 assert.equal(f.calls.length,previous+1);
});


test('review filters and polling replace all grouped record bodies together', async () => {
 const f=fixture(async()=>response('reviews'),'/harness/reviews/','table');
 await f.control.load('/harness/reviews/?q=page&size=10',true);
 assert.equal(f.rows.innerHTML,'reviewstable');
 assert.equal(f.results.style.minHeight,'640px');
 assert.deepEqual(f.history,['/harness/reviews/?q=page&size=10']);
});
