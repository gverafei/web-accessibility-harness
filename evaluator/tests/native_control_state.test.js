const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),native=require('../native_control_state');
async function withPage(fn){const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});try{await fn(await browser.newPage());}finally{await browser.close();}}
test('observed disabled placeholder selection survives HTML serialization without mutation',()=>withPage(async page=>{
 await page.setContent('<form id="signup"><select id="date" name="date"><option value="" disabled>Month</option><option value="Jan">January</option></select></form>');
 await page.locator('select').evaluate(el=>el.selectedIndex=0);
 const html=await page.content(),reference=await native.capture(page);assert.equal(await page.content(),html);
 assert.equal(reference.records[0].state.value,'');assert.deepEqual(reference.records[0].state.selected_indexes,[0]);
 await page.setContent(html);assert.equal(await page.locator('select').inputValue(),'Jan');
 assert.equal((await native.restore(page,reference)).status,'completed');assert.equal(await page.locator('select').inputValue(),'');
 assert.equal(await page.content(),html);assert.deepEqual((await native.capture(page)).records,reference.records);
}));
test('canonical persisted JSON key order does not change control contracts or observed state',()=>withPage(async page=>{
 await page.setContent('<select id="month"><option disabled value="">Month</option><option value="Jan">January</option></select>');await page.locator('select').evaluate(el=>el.selectedIndex=0);
 const observed=await native.capture(page),html=await page.content();
 const sort=v=>Array.isArray(v)?v.map(sort):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])])):v;
 const saved=JSON.parse(JSON.stringify(sort(observed)));assert.deepEqual(saved,observed);await page.setContent(html);
 assert.equal((await native.restore(page,saved)).status,'completed');assert.equal(await page.locator('select').inputValue(),'');assert.equal(await page.content(),html);
}));
test('restoration preserves observed values, checked and indeterminate properties without firing events',()=>withPage(async page=>{
 await page.setContent('<input id="name" value="default"><input id="flag" type="checkbox"><textarea id="text">default</textarea>');
 await page.evaluate(()=>{document.querySelector('#name').value='observed';const flag=document.querySelector('#flag');flag.checked=true;flag.indeterminate=true;document.querySelector('#text').value='observed text';});
 const html=await page.content(),reference=await native.capture(page);await page.setContent(html);
 await page.evaluate(()=>{window.events=[];for(const name of ['input','change','click'])document.addEventListener(name,e=>window.events.push(e.type));});
 const result=await native.restore(page,reference);assert.equal(result.status,'completed');assert.deepEqual(await page.evaluate(()=>window.events),[]);
 assert.deepEqual((await native.capture(page)).records,reference.records);assert.equal(await page.content(),html);
}));
test('multiple selections and explicit no-selection state are restored exactly',()=>withPage(async page=>{
 await page.setContent('<select id="many" multiple><option>a</option><option>b</option><option>c</option></select><select id="none"><option>a</option><option>b</option></select>');
 await page.evaluate(()=>{const a=document.querySelector('#many');a.options[0].selected=true;a.options[2].selected=true;document.querySelector('#none').selectedIndex=-1;});
 const reference=await native.capture(page),html=await page.content();await page.setContent(html);
 assert.equal((await native.restore(page,reference)).status,'completed');assert.deepEqual((await native.capture(page)).records,reference.records);
}));
test('a changed candidate contract is recorded without replacing its generated state',()=>withPage(async page=>{
 await page.setContent('<form action="/submit"><input id="value" value="source"></form>');const reference=await native.capture(page);
 await page.locator('input').evaluate(el=>{el.setAttribute('value','candidate');el.value='candidate';});
 const result=await native.restore(page,reference);assert.equal(result.status,'partial');assert.equal(result.results[0].status,'not_matched');assert.equal(await page.locator('input').inputValue(),'candidate');
}));
test('duplicate IDs never receive guessed native state',()=>withPage(async page=>{
 await page.setContent('<input id="duplicate" value="one"><input id="duplicate" value="two">');const reference=await native.capture(page);
 const result=await native.restore(page,reference);assert.equal(result.status,'partial');assert.ok(result.results.every(x=>x.status==='not_matched'));
}));
test('equivalent absolute form destinations and case normalization retain the observed state',()=>withPage(async page=>{
 await page.route('https://forms.example/',r=>r.fulfill({contentType:'text/html',body:'<form id="form" action="/submit" method="POST"><input id="field" type="TEXT" value="default"><button formaction="/alternate">Save</button></form>'}));
 await page.goto('https://forms.example/');await page.locator('input').evaluate(el=>el.value='observed');const reference=await native.capture(page);
 const html=(await page.content()).replace('action="/submit"','action="https://forms.example/submit"').replace('formaction="/alternate"','formaction="https://forms.example/alternate"').replace('method="POST"','method="post"').replace('type="TEXT"','type="text"');
 await page.setContent(html);assert.equal((await native.restore(page,reference)).status,'completed');assert.equal(await page.locator('input').inputValue(),'observed');
 assert.equal(await page.content(),html);
}));
test('disabled fieldset or changed field constraints cannot receive substituted source state',()=>withPage(async page=>{
 await page.setContent('<fieldset disabled><input id="field" type="number" min="1" max="5" value="2"></fieldset>');const reference=await native.capture(page);
 await page.locator('fieldset').evaluate(el=>el.removeAttribute('disabled'));
 assert.equal((await native.restore(page,reference)).results[0].status,'not_matched');
 await page.locator('fieldset').evaluate(el=>el.setAttribute('disabled',''));await page.locator('input').evaluate(el=>el.max='9');
 assert.equal((await native.restore(page,reference)).results[0].status,'not_matched');
}));
test('invalid option indices fail typed validation and legacy absence is explicit',()=>withPage(async page=>{
 await page.setContent('<select><option>one</option></select>');const reference=await native.capture(page);reference.records[0].state.selected_indexes=[9];
 await assert.rejects(native.restore(page,reference),/Invalid native option selection/);
 assert.equal((await native.restore(page,null)).status,'not_recorded');
}));
test('phase fingerprint detects secondary multiple selections and indeterminate state with unchanged HTML',()=>withPage(async page=>{
 const phase=require('../phase_evidence');
 await page.setContent('<select multiple><option selected>a</option><option>b</option></select><input type="checkbox">');
 const html=await page.content(),before=await phase.observe(page,'before');
 await page.evaluate(()=>document.querySelector('select').options[1].selected=true);
 assert.equal(await page.content(),html);assert.equal(await page.locator('select').inputValue(),'a');
 const selected=await phase.observe(page,'selected');assert.notEqual(before.sha256,selected.sha256);
 await page.evaluate(()=>document.querySelector('input').indeterminate=true);
 assert.equal(await page.content(),html);assert.notEqual(selected.sha256,(await phase.observe(page,'indeterminate')).sha256);
}));
test('original-origin audit restores the recorded placeholder before capture and both evaluators',()=>withPage(async page=>{
 const fs=require('node:fs'),path=require('node:path'),root=fs.mkdtempSync('/results/native-control-integration-');
 const evidence=require('../harness_evidence'),publicUrl=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  await page.setContent('<html lang="en"><head><title>Signup</title></head><body><main><label for="month">Birthday month</label><select id="month"><option disabled value="">Month</option><option value="Jan">January</option></select></main></body></html>');
  await page.locator('select').evaluate(el=>el.selectedIndex=0);
  const reference=await native.capture(page),document=await page.content(),file=path.join(root,'manifest.json');
  fs.writeFileSync(file,JSON.stringify({version:require('../origin_snapshot').VERSION,origin:'https://signup.example/',document,assets:[],native_control_reference:reference}));
  const result=await require('../origin_snapshot').run(file,path.join(root,'audit'));
  assert.equal(result.status,'completed');assert.equal(result.transport.native_control_restoration.status,'completed');
  assert.equal(result.transport.phase_evidence.stable,true);assert.equal(result.transport.visible.native_control_reference.records[0].state.value,'');
  assert.deepEqual(result.transport.visible.native_control_reference.records[0].state.selected_indexes,[0]);
  assert.equal(JSON.parse(fs.readFileSync(file,'utf8')).document,document);
  assert.deepEqual(result.transport.visible.native_control_reference.records,reference.records);
 }finally{evidence.publicUrl=publicUrl;fs.rmSync(root,{recursive:true,force:true});}
}));
