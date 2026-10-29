const test=require('node:test'),assert=require('node:assert/strict');
const {recordPage}=require('../app/static/js/record_lists.js');
test('pagination searches complete groups and keeps actions together',()=>{
 const groups=Array.from({length:13},(_,i)=>({text:i%2?'Luna':'Haiku',rows:['data'+i,'actions'+i]}));
 const page=recordPage(groups,'Luna',2,5);assert.equal(page.total,6);assert.equal(page.items.length,1);assert.equal(page.items[0].rows.length,2);
 assert.equal(recordPage(groups,'',99,5).page,3);assert.equal(recordPage(groups,'absent',1,25).total,0);
});
test('history controls keep records and actions together after refresh and filtering',()=>{
 const {initHistoryPagination}=require('../app/static/js/record_lists.js');
 const entries=Array.from({length:12},(_,i)=>({textContent:'URL '+i+' actions',dataset:{searchText:i%2?'opus high Level 5':'luna low Level 2'},hidden:false}));
 const listeners={},input={value:'',addEventListener:(name,fn)=>listeners[name]=fn};
 const size={value:5,addEventListener:(name,fn)=>listeners['size'+name]=fn};
 const status={},buttons=['first','previous','next','last'].map(action=>({dataset:{pageAction:action},addEventListener:(name,fn)=>listeners[action]=fn}));
 const table={querySelectorAll:()=>entries,dispatchEvent(){},addEventListener:(name,fn)=>listeners[name]=fn};
 const pager={dataset:{table:'.table',input:'filter'},querySelector:selector=>selector==='select'?size:status,querySelectorAll:()=>buttons,getBoundingClientRect:()=>({top:100})};
 const env={document:{querySelector:()=>table,getElementById:()=>input,documentElement:{lang:'es'}},location:{href:'http://localhost/'},history:{replaceState(){}},requestAnimationFrame:fn=>fn(),scrollBy(){}};
 initHistoryPagination(pager,env);assert.equal(entries.filter(e=>!e.hidden).length,5);assert.match(status.textContent,/1–5 \/ 12/);
 listeners.next();assert.deepEqual(entries.filter(e=>!e.hidden),entries.slice(5,10));
 listeners['history:changed']();assert.deepEqual(entries.filter(e=>!e.hidden),entries.slice(5,10));
 input.value='opus';listeners.input();assert.equal(entries.filter(e=>!e.hidden).length,5);assert.match(status.textContent,/\/ 6/);
 listeners.last();assert.equal(entries.filter(e=>!e.hidden).length,1);assert.equal(buttons[3].disabled,true);
 input.value='missing';listeners.input();assert.match(status.textContent,/0–0 \/ 0/);assert.equal(entries.filter(e=>!e.hidden).length,0);
});
test('slider dropdowns combine exact strategies and preservation on the same condition',()=>{
 const {matchesHistoryFilters}=require('../app/static/js/record_lists.js');
 const entry={dataset:{filterPairs:JSON.stringify([['low','15'],['high','55'],['dynamic','105']])}};
 assert.equal(matchesHistoryFilters(entry,'high','55'),true);
 assert.equal(matchesHistoryFilters(entry,'high','15'),false);
 assert.equal(matchesHistoryFilters(entry,'dynamic','105'),true);
 assert.equal(matchesHistoryFilters(entry,'','55'),true);
 assert.equal(matchesHistoryFilters({dataset:{filterPairs:'[]'}},'low',''),false);
 assert.equal(matchesHistoryFilters({dataset:{filterPairs:'invalid'}},'',''),true);
});
test('evaluation dropdowns match status and acquisition, without remediation strategy',()=>{
 const {matchesEvaluationFilters}=require('../app/static/js/record_lists.js');
 const entry={dataset:{status:'failed',acquisition:'web'}};
 assert.equal(matchesEvaluationFilters(entry,'failed','web'),true);
 assert.equal(matchesEvaluationFilters(entry,'completed','web'),false);
 assert.equal(matchesEvaluationFilters(entry,'failed','imported'),false);
 assert.equal(matchesEvaluationFilters(entry,'','web'),true);
 assert.equal(matchesEvaluationFilters(entry,'',''),true);
});

test('RAG filter uses retrieved evidence rather than an enabled setting',()=>{
 const {matchesRagFilter}=require('../app/static/js/record_lists.js');
 const used={dataset:{ragUsed:'true',ragEnabled:'true'}},empty={dataset:{ragUsed:'false',ragEnabled:'true'}};
 assert.equal(matchesRagFilter(used,'true'),true);assert.equal(matchesRagFilter(empty,'true'),false);
 assert.equal(matchesRagFilter(empty,'false'),true);assert.equal(matchesRagFilter(used,'false'),false);
 assert.equal(matchesRagFilter(used,''),true);assert.equal(matchesRagFilter({dataset:{}},'false'),false);
});

test('page-size preference crosses histories and accepts all six sizes',()=>{
 const {savedRecordPageSize,saveRecordPageSize,RECORD_PAGE_SIZES}=require('../app/static/js/record_lists.js');
 const data=new Map(),env={localStorage:{getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)}};
 assert.deepEqual(RECORD_PAGE_SIZES,[5,10,25,50,100,200]);
 assert.equal(savedRecordPageSize(env),5);
 for(const size of RECORD_PAGE_SIZES){
  saveRecordPageSize(env,size);assert.equal(savedRecordPageSize(env,5),size);
  const otherPage={localStorage:env.localStorage};assert.equal(savedRecordPageSize(otherPage),size);
  assert.equal(recordPage(Array.from({length:220},()=>({text:'row'})),'',1,size).items.length,size);
 }
 saveRecordPageSize(env,999);assert.equal(savedRecordPageSize(env),200);
 const blocked={get localStorage(){throw Error('unavailable');}};
 assert.equal(savedRecordPageSize(blocked,100),100);saveRecordPageSize(blocked,25);
 assert.equal(savedRecordPageSize(blocked,999),5);
});


test('review queues default to pending and filter/page locally with shared URL parameters',()=>{
 const {initHistoryPagination}=require('../app/static/js/record_lists.js');
 function setup(query=''){
  const entries=Array.from({length:24},(_,i)=>({textContent:'page '+i,dataset:{status:i<16?'pending':i<20?'in_progress':'submitted',kind:i%2?'verification':'acquisition'},hidden:false,position:{textContent:''},querySelector(){return this.position;}}));
  const listeners={},input={value:'',addEventListener:(name,fn)=>listeners[name]=fn};
  const size={value:5,addEventListener:(name,fn)=>listeners['size'+name]=fn},caption={};
  const state={value:'pending',options:['','pending','in_progress','submitted'].map(value=>({value})),addEventListener:(name,fn)=>listeners['status'+name]=fn};
  const kind={value:'',options:['','verification','acquisition'].map(value=>({value})),addEventListener:(name,fn)=>listeners['kind'+name]=fn};
  const bar={querySelector:selector=>({'[data-history-status]':state,'[data-history-kind]':kind}[selector])};
  const form={addEventListener:(name,fn)=>listeners['form'+name]=fn};
  const buttons=['first','previous','next','last'].map(action=>({dataset:{pageAction:action},addEventListener:(name,fn)=>listeners[action]=fn}));
  const table={querySelectorAll:()=>entries,dispatchEvent(){},addEventListener:(name,fn)=>listeners[name]=fn};
  const pager={dataset:{table:'.table',input:'review-search',standardParams:'true'},closest:selector=>selector==='.list-filter-bar'?bar:form,querySelector:selector=>selector==='select'?size:caption,querySelectorAll:()=>buttons,getBoundingClientRect:()=>({top:100})};
  const env={document:{querySelector:()=>table,getElementById:()=>input,documentElement:{lang:'en'}},location:{href:'http://localhost/harness/reviews/reviewers/1'+query},history:{replaceState(_s,_t,url){env.location.href=String(url);}},requestAnimationFrame:fn=>fn(),scrollBy(){},fetch(){throw Error('Pagination must not fetch');}};
  initHistoryPagination(pager,env);
  return {entries,listeners,state,kind,env,caption,buttons,input,size,visible:()=>entries.filter(row=>!row.hidden)};
 }
 const a=setup();assert.equal(a.state.value,'pending');assert.match(a.caption.textContent,/\/ 16/);
 assert.equal(a.visible()[0].position.textContent,'1');
 a.listeners.next();assert.equal(a.visible()[0],a.entries[5]);assert.equal(a.visible()[0].position.textContent,'6');assert.equal(new URL(a.env.location.href).searchParams.get('page'),'2');
 a.kind.value='verification';a.listeners.kindchange();assert.equal(a.visible()[0].position.textContent,'1');assert.equal(a.visible().length,5);assert.ok(a.visible().every(row=>row.dataset.kind==='verification'));
 a.listeners.last();assert.equal(a.visible().length,3);assert.equal(a.buttons[3].disabled,true);
 a.state.value='submitted';a.listeners.statuschange();assert.equal(a.visible().length,2);assert.ok(a.visible().every(row=>row.dataset.status==='submitted'));
 a.input.value='missing';a.listeners.input();assert.equal(a.visible().length,0);assert.match(a.caption.textContent,/0–0 \/ 0/);
 let prevented=false;a.listeners.formsubmit({preventDefault(){prevented=true;}});assert.equal(prevented,true);
 const all=setup('?status=&size=10&page=2');assert.equal(all.state.value,'');assert.equal(all.visible().length,10);assert.equal(all.visible()[0],all.entries[10]);
 const legacy=setup('?status=assigned');assert.equal(legacy.state.value,'pending');
 const saved=setup('?status=submitted&kind=verification');assert.equal(saved.visible().length,2);assert.equal(saved.kind.value,'verification');
});

test('evaluation search supports displayed hash IDs and plain IDs',()=>{
 const groups=[{text:'#407 Consultant completed https://www.consultant.ru/'},{text:'#408 Example completed https://example.org/'}];
 for(const query of ['407','#407','consultant'])assert.deepEqual(recordPage(groups,query,1,5).items,[groups[0]]);
});


test('dataset filters keep the complete analytical population across display pages',()=>{
 const {initHistoryPagination}=require('../app/static/js/record_lists.js');
 const entries=Array.from({length:16},(_,i)=>({dataset:{searchText:'page '+i,collection:i<12?'generated':'evaluation',model:i<12?'Luna high':'',completion:i<10?'paired adjudicated':''},hidden:false}));
 const listeners={},input={value:'',addEventListener:(event,fn)=>listeners[event]=fn};
 const size={value:5,addEventListener:(event,fn)=>listeners['size'+event]=fn},caption={},empty={hidden:true};
 const select=(key,values,match)=>({value:'',dataset:{historyFilter:key,historyMatch:match},options:values.map(value=>({value})),addEventListener:(event,fn)=>listeners[key+event]=fn});
 const collection=select('collection',['','generated','evaluation']),model=select('model',['','Luna high']),completion=select('completion',['','paired','adjudicated'],'tokens');
 const custom=[collection,model,completion];
 const bar={querySelector:()=>null,querySelectorAll:()=>custom};
 const form={addEventListener:(event,fn)=>listeners['form'+event]=fn};
 const table={querySelectorAll:()=>entries,querySelector:()=>empty,dispatchEvent(){},addEventListener:(event,fn)=>listeners[event]=fn};
 const buttons=['first','previous','next','last'].map(action=>({dataset:{pageAction:action},addEventListener:(_event,fn)=>listeners[action]=fn}));
 const pager={dataset:{table:'#scores',input:'score-search',standardParams:'true'},closest:selector=>selector==='.list-filter-bar'?bar:form,querySelector:selector=>selector==='select'?size:caption,querySelectorAll:()=>buttons,getBoundingClientRect:()=>({top:100})};
 const env={document:{querySelector:()=>table,getElementById:()=>input,documentElement:{lang:'en'}},location:{href:'http://localhost/harness/reviews/analytics/dataset?collection=generated&size=5&page=2'},history:{replaceState(_s,_t,url){env.location.href=String(url);}},requestAnimationFrame:fn=>fn(),scrollBy(){},fetch(){throw Error('Local filtering must not fetch');}};
 const controller=initHistoryPagination(pager,env);
 assert.equal(collection.value,'generated');assert.equal(controller.filteredEntries.length,12);
 assert.deepEqual(entries.filter(row=>!row.hidden),entries.slice(5,10));
 listeners.next();assert.equal(controller.filteredEntries.length,12);assert.equal(entries.filter(row=>!row.hidden).length,2);
 completion.value='paired';listeners.completionchange();assert.equal(controller.filteredEntries.length,10);assert.match(caption.textContent,/1–5 \/ 10/);
 completion.value='adjudicated';listeners.completionchange();assert.equal(controller.filteredEntries.length,10);
 model.value='Luna high';listeners.modelchange();assert.equal(controller.filteredEntries.length,10);
 input.value='not found';listeners.input();assert.equal(controller.filteredEntries.length,0);assert.equal(empty.hidden,false);
 input.value='page 1';listeners.input();assert.equal(controller.filteredEntries.length,1);assert.equal(empty.hidden,true);
 assert.equal(new URL(env.location.href).searchParams.get('model'),'Luna high');
 assert.equal(new URL(env.location.href).searchParams.get('page'),'1');
});

test('remediation ID search distinguishes run IDs from any saved iteration ID',()=>{
 const group=(run,iterations,text)=>({text,entry:{dataset:{searchIds:JSON.stringify({run:String(run),iterations:iterations.map(String)})}}});
 const groups=[group(975,[2110,2112],'Ubuntu B-0037'),group(1975,[975],'Other domain'),group(211,[999],'Other run')];
 const matches=q=>recordPage(groups,q,1,50).items.map(g=>JSON.parse(g.entry.dataset.searchIds).run);
 for(const q of ['run:975','run #975','RUN975','corrida 975','ejecución:975'])assert.deepEqual(matches(q),['975']);
 for(const q of ['iter:2110','iteration 2110','iteración #2110','2112'])assert.deepEqual(matches(q),['975']);
 assert.deepEqual(matches('iter:975'),['1975']);
 assert.deepEqual(matches('#975'),['975','1975']);
 assert.deepEqual(matches('run:000975'),['975']);
 assert.deepEqual(matches('run:2110'),[]);
 assert.deepEqual(matches('iter:211'),[]);
 assert.deepEqual(matches('B-0037'),['975']);
 assert.deepEqual(matches('ubuntu'),['975']);
 assert.equal(recordPage([{text:'example975.org'}],'975',1,5).total,1);
});
