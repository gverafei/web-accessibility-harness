const test=require('node:test'),assert=require('node:assert/strict');
const {summarize,observe}=require('../phase_evidence');
test('all measurement phases must agree and incomplete evidence is not stable',()=>{
 const phases=['before_capture','after_capture','after_axe','after_lighthouse'].map(phase=>({phase,sha256:'same'}));
 assert.equal(summarize(phases).stable,true);
 assert.equal(summarize(phases.slice(0,3)).stable,false);
 phases[2].sha256='changed';assert.equal(summarize(phases).stable,false);
});
test('computed style or native value changes alter the fingerprint',async()=>{
 let state={origin:'https://example.com',url:'https://example.com/',html:'<input>',styles:[['input','black','original',[]]]};
 const page={evaluate:async()=>state};
 const before=await observe(page,'before');state={...state,styles:[['input','black','changed',[]]]};
 assert.notEqual((await observe(page,'after')).sha256,before.sha256);
});

test('large repeated CSS stays compact and complete value changes remain visible',async()=>{
 const {chromium}=require('playwright');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage();
  await page.setContent('<style>:root{--large:url("data:image/svg+xml,'+ 'a'.repeat(12000)+'")}div{background-image:var(--large)}</style>'+ '<div>same</div>'.repeat(100));
  const before=await observe(page,'before');
  assert.ok(JSON.stringify(before.layoutEntries).length<2000000);
  await page.evaluate(()=>document.documentElement.style.setProperty('--large','url("data:image/svg+xml,'+ 'a'.repeat(11999)+'b")'));
  const after=await observe(page,'after');
  assert.notEqual(before.sha256,after.sha256);
  const oldValue=before.layoutEntries.find(row=>row[0]==='DIV')[5];
  const newValue=after.layoutEntries.find(row=>row[0]==='DIV')[5];
  assert.notEqual(oldValue.sha256,newValue.sha256);assert.equal(oldValue.characters,newValue.characters);
 }finally{await browser.close();}
});

test('serialized browser evidence preserves the complete fingerprint',async()=>{
 const state={origin:'https://example.com',url:'https://example.com/',html:'<input>',styles:[['input','black','value',[]]]};
 const direct=await observe({evaluate:async()=>state},'before');
 const serialized=await observe({evaluate:async()=>JSON.stringify(state)},'before');
 assert.equal(serialized.sha256,direct.sha256);assert.deepEqual(serialized.layoutEntries,direct.layoutEntries);
});

test('interned CSS pairs preserve diagnostics and measured fingerprints',async()=>{
 const properties=[['outline-color','black'],['--theme','same-value']];
 const row=['DIV','visible',0,[0,1]];
 const packed={origin:'https://example.com',url:'https://example.com/',html:'<div></div>',styles:[row],cssProperties:properties};
 const expanded={...packed,styles:[[...row.slice(0,-1),properties]]};delete expanded.cssProperties;
 const result=await observe({evaluate:async()=>JSON.stringify(packed)},'before');
 const reference=await observe({evaluate:async()=>JSON.stringify(expanded)},'before');
 assert.equal(result.sha256,reference.sha256);assert.deepEqual(result.layoutEntries,reference.layoutEntries);
});

test('DOM diagnostics distinguish insertion from shifted indexes',()=>{
 const phases=['before','capture','axe','lighthouse'].map((phase,index)=>({phase,sha256:index?'different':'original',domEntries:index?[['LINK',[['rel','prefetch']],[]],['BODY',[],[]],['SPAN',[],['new']]]:[['BODY',[],[]]]}));
 const result=summarize(phases);assert.equal(result.stable,false);assert.equal(result.dom_changes[0].added.length,2);assert.equal(result.dom_changes[0].removed.length,0);
});

test('observing custom elements never runs their constructors or mutates live content',async()=>{
 const {chromium}=require('playwright');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage();await page.setContent('<body><main><h1>Content</h1><probe-island></probe-island></main><script>window.constructions=0;customElements.define("probe-island",class extends HTMLElement{constructor(){super();window.constructions++;queueMicrotask(()=>{const notification=document.createElement("span");notification.textContent="Notification";document.body.append(notification);});}});</script></body>');
  const before=await page.evaluate(()=>({constructions:window.constructions,html:document.body.innerHTML}));
  const first=await observe(page,'before');const second=await observe(page,'after');
  const after=await page.evaluate(()=>({constructions:window.constructions,html:document.body.innerHTML}));
  assert.deepEqual(after,before);assert.equal(first.sha256,second.sha256);
 }finally{await browser.close();}
});

test('head prefetch hints are diagnostic but their actual CSS effects still invalidate measurement',async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{const page=await browser.newPage();await page.setContent('<head><title>Hints</title></head><body><h1>Content</h1></body>');
 const before=await observe(page,'before');await page.evaluate(()=>{const e=document.createElement('link');e.rel='prefetch';e.href='/next';document.head.append(e);});
 const after=await observe(page,'after');assert.equal(before.sha256,after.sha256);assert.equal(after.resource_hints.length,1);
 await page.setContent('<head><title>Hints with style</title><style>head:has(link[rel=prefetch]) + body{color:red}</style></head><body><h1>Content</h1></body>');
 const styledBefore=await observe(page,'before');await page.evaluate(()=>{const e=document.createElement('link');e.rel='prefetch';e.href='/next';document.head.append(e);});
 assert.notEqual(styledBefore.sha256,(await observe(page,'after')).sha256);
 }finally{await browser.close();}
});


test('head script preload is diagnostic but stylesheet preload and visible CSS effects remain protected',async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();
 for(const rel of ['preload','modulepreload']){
  await page.setContent('<head><title>Hints</title></head><body><h1>Content</h1></body>');
  const before=await observe(page,'before');await page.evaluate(rel=>{const e=document.createElement('link');e.rel=rel;e.as='script';e.href='/app.js';document.head.append(e);},rel);
  const after=await observe(page,'after');assert.equal(before.sha256,after.sha256);assert.equal(after.resource_hints.length,1);
 }
 await page.setContent('<head><style>head:has(link[as=script]) + body{color:red}</style></head><body><h1>Content</h1></body>');
 const painted=await observe(page,'before');await page.evaluate(()=>{const e=document.createElement('link');e.rel='preload';e.as='script';e.href='/app.js';document.head.append(e);});
 assert.notEqual(painted.sha256,(await observe(page,'after')).sha256);
 await page.setContent('<head></head><body><h1>Content</h1></body>');
 const styled=await observe(page,'before');await page.evaluate(()=>{const e=document.createElement('link');e.rel='preload';e.as='style';e.href='/app.css';document.head.append(e);});
 assert.notEqual(styled.sha256,(await observe(page,'after')).sha256);
 }finally{await browser.close();}
});

test('actual outline and margin changes still invalidate the measured state',async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();
  for(const property of ['outline:10px solid red','margin-left:20px']){
   await page.setContent('<style>input[style]{'+property+'}</style><input>');
   const before=await observe(page,'before');
   await page.evaluate(()=>document.querySelector('input').setAttribute('style',''));
   const after=await observe(page,'after');
   assert.equal(before.dom_sha256,after.dom_sha256);
   assert.notEqual(before.layout_sha256,after.layout_sha256);
   assert.notEqual(before.sha256,after.sha256);
  }
 }finally{await browser.close();}
});

test('class token reorder is stable but order-sensitive CSS effects remain protected',async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();
  for(const styled of [false,true]){
   await page.setContent((styled?'<style>h1[class="a b"]{color:red}h1[class="b a"]{color:blue}</style>':'')+'<h1 class="a b">Content</h1>');
   const before=await observe(page,'before');await page.evaluate(()=>document.querySelector('h1').className='b a');const after=await observe(page,'after');
   assert.equal(before.dom_sha256,after.dom_sha256);
   if(styled)assert.notEqual(before.sha256,after.sha256);else assert.equal(before.sha256,after.sha256);
  }
 }finally{await browser.close();}
});
