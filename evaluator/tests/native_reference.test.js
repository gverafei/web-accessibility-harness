const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
test('native reference rebuilds after property-only control changes during capture',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/native-reference-properties-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});await require('../measurement_state').install(page);
  await page.route('https://native-state.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><input id="state" value="declared"></body></html>'}));
  await page.goto('https://native-state.example/');
  const screenshot=page.screenshot.bind(page);let calls=0;
  page.screenshot=async options=>{const result=await screenshot(options);if(++calls===1)await page.locator('input').evaluate(el=>el.value='late property');return result;};
  const reference=await require('../native_reference').capture(page,{finish:async()=>({})},root+'/page.jpg');
  assert.equal(reference.stabilization_attempts,2);assert.equal(reference.native_control_reference.records[0].state.value,'late property');
  assert.equal(reference.html,await page.content());assert.ok(reference.html.includes('value="declared"'));
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});
test('native reference finishes delayed resources before freezing one carousel state',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/native-reference-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();
  await require('../measurement_state').install(page);
  await page.route('https://acquisition.example/',route=>route.fulfill({contentType:'text/html',body:'<html><body style="height:2200px"><p id="slide">Slide 0</p><script>let tick=0;setInterval(()=>document.querySelector("#slide").textContent="Slide "+(++tick),40)</script></body></html>'}));
  await page.goto('https://acquisition.example/');
  let finishedSlide;
  const collector={finish:async()=>{await new Promise(r=>setTimeout(r,300));finishedSlide=await page.locator('#slide').textContent();return {version:'test-delayed-resource'};}};
  const reference=await require('../native_reference').capture(page,collector,root+'/page.jpg');
  const retained=await page.locator('#slide').textContent();
  assert.notEqual(finishedSlide,'Slide 0');
  assert.ok(reference.html.includes(retained));
  assert.ok(JSON.stringify(reference.visible).includes(retained));
  assert.equal(reference.measurement_state.intervals,1);
  await page.waitForTimeout(180);
  assert.equal(await page.content(),reference.html);
  const AxeBuilder=require('@axe-core/playwright').default;
  const audit=await new AxeBuilder({page}).withTags(['wcag2a']).analyze();
  assert.ok(Array.isArray(audit.violations));
  assert.equal(await page.content(),reference.html);
  assert.equal(reference.screenshot.complete,true);
  assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('native reference rebuilds all evidence after a late document mutation',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/native-reference-late-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await require('../measurement_state').install(page);
  await page.route('https://late.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><p>Original</p></body></html>'}));
  await page.goto('https://late.example/');
  const screenshot=page.screenshot.bind(page);let calls=0;
  page.screenshot=async options=>{const result=await screenshot(options);if(++calls===1)await page.evaluate(()=>{const p=document.createElement('p');p.textContent='Late fetch content';document.body.append(p);});return result;};
  const finishes=[];const collector={finish:async(options={})=>{finishes.push(options);return {version:'fixture',late_resources:finishes.length};}};
  const reference=await require('../native_reference').capture(page,collector,root+'/page.jpg');
  assert.equal(reference.stabilization_attempts,2);
  assert.ok(reference.html.includes('Late fetch content'));
  assert.ok(JSON.stringify(reference.visible).includes('Late fetch content'));
  assert.equal(await page.content(),reference.html);
  assert.equal(finishes[0].close,false);
  assert.deepEqual(finishes.at(-1),{});
  assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('native reference rejects persistent mutation instead of fabricating stability',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/native-reference-unstable-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await require('../measurement_state').install(page);
  await page.route('https://unstable.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><p>Unstable</p></body></html>'}));
  await page.goto('https://unstable.example/');
  const screenshot=page.screenshot.bind(page);let calls=0;
  page.screenshot=async options=>{const result=await screenshot(options);await page.evaluate(n=>document.body.dataset.revision=String(n),++calls);return result;};
  await assert.rejects(require('../native_reference').capture(page,{finish:async()=>({})},root+'/page.jpg'),/bounded stabilization/);
  assert.equal(calls,3);
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('segment-activated delayed images decode before the native reference is measured',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/native-segment-image-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await require('../measurement_state').install(page);
  await page.route('https://segment-image.example/image.svg',async r=>{await new Promise(resolve=>setTimeout(resolve,900));await r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="green"/></svg>'});});
  await page.route('https://segment-image.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><div style="height:2200px"></div><img id="late" width="160" height="160" alt="Green square"><script>const img=document.querySelector("#late");const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){img.src="/image.svg";observer.disconnect();}});observer.observe(img);</script></body></html>'}));
  await page.goto('https://segment-image.example/');
  const reference=await require('../native_reference').capture(page,{finish:async()=>({})},root+'/page.jpg',{network_idle_timeout_ms:2500,dom_stability_timeout_ms:2000,dom_stability_window_ms:100});
  assert.equal(reference.resource_stability.stable,true);
  assert.equal(await page.locator('#late').evaluate(e=>e.naturalWidth),160);
  const phase=require('../phase_evidence'),before=await phase.observe(page,'before');
  await page.waitForTimeout(1000);
  assert.equal((await phase.observe(page,'after')).sha256,before.sha256);
  assert.deepEqual(await page.evaluate(()=>[scrollX,scrollY]),[0,0]);
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('lazy images appended after initial traversal are settled on the final frozen document',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/native-final-segment-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});await require('../measurement_state').install(page);
  await page.route('https://final-segment.example/image.svg',async r=>{await new Promise(resolve=>setTimeout(resolve,500));await r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"/>'});});
  await page.route('https://final-segment.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><main>Initial page</main></body></html>'}));await page.goto('https://final-segment.example/');
  let calls=0;const collector={finish:async()=>{if(++calls===1)await page.evaluate(()=>{document.body.insertAdjacentHTML('beforeend','<div style="height:14000px"></div><img id="late" loading="lazy" src="/image.svg" width="160" height="160" alt="Square">');});return {};}};
  const result=await require('../native_reference').capture(page,collector,root+'/page.jpg',{network_idle_timeout_ms:100,dom_stability_timeout_ms:2000,dom_stability_window_ms:100});
  assert.equal(await page.locator('#late').evaluate(e=>e.naturalWidth),160);
  assert.ok(result.segment_preparation.frozen.prepared_segments>result.segment_preparation.initial.prepared_segments);
  assert.equal(await page.locator('#late').getAttribute('loading'),'lazy');
  const phases=require('../phase_evidence'),before=await phases.observe(page,'before');await page.waitForTimeout(600);
  assert.equal((await phases.observe(page,'after')).sha256,before.sha256);
  assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});
