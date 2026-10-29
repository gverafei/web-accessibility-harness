const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright');const {visibleEvidence,replayCheck}=require('../replay_admission');
test('local replay admission rejects outside URLs before launching',async()=>{
 await assert.rejects(replayCheck('https://example.com/'),/frozen local snapshot/);
 await assert.rejects(replayCheck('http://dataset-server:8080/other'),/frozen local snapshot/);
});
test('authored preload none is observed as deferred, while errors and unknown blob sources remain broken',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();await page.route('https://deferred.example/missing.mp4',r=>r.abort());
  await page.setContent('<video width="200" height="100" preload="none"><source src="https://deferred.example/later.mp4"></video><video width="200" height="100" preload="auto" src="https://deferred.example/missing.mp4"></video><video width="200" height="100" preload="none" src="blob:https://deferred.example/unknown"></video>');
  await page.waitForFunction(()=>document.querySelectorAll('video')[1].error);
  const result=await visibleEvidence(page);assert.equal(result.visible_media,3);assert.equal(result.deferred_media,1);assert.equal(result.broken_media,2);assert.equal(result.media_descriptors[0].state,'deferred');assert.deepEqual(result.media_descriptors[0].identity.sources,['https://deferred.example/later.mp4']);
 }finally{await browser.close();}
});
test('visible evidence detects a script-hidden page despite a full DOM',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
 const page=await browser.newPage();await page.setContent('<html><body><main><h1>Courses</h1><button>Learn</button><a href="/help">Help</a></main></body></html>');
 const a=await visibleEvidence(page);assert.ok(a.text.includes('Courses'));assert.equal(a.controls.length,2);
 await page.evaluate(()=>document.body.style.opacity='0');const b=await visibleEvidence(page);
 assert.equal(b.controls.length,0);
 }finally{await browser.close();}
});
test('visible media excludes only explicit unnamed one-pixel images and keeps image controls',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
 const page=await browser.newPage();
 await page.setContent('<img alt="" width="1" height="1" src="missing-pixel"><img alt="Brand" width="1" height="1" src="missing-brand"><img width="1" height="1" src="missing-unknown"><input type="image" src="missing-submit">');
 const result=await visibleEvidence(page);
 assert.equal(result.visible_images,2);assert.equal(result.broken_images,2);
 assert.ok(result.controls.some(c=>c.startsWith('INPUT|image|')));
 }finally{await browser.close();}
});

test('CSS-sized decorative pixels are excluded without hiding broken content or image controls',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage();
  await page.setContent('<img alt="" src="" style="width:1px!important;height:1px!important;position:absolute;top:0">'+
   '<img src="" style="width:1px;height:1px"><img alt="Brand" src="" style="width:1px;height:1px">'+
   '<img alt="" width="1" height="1" src="" style="width:80px;height:80px">'+
   '<a href="/help"><img alt="" src="" style="width:1px;height:1px"></a>'+
   '<img alt="" role="button" src="" style="width:1px;height:1px">');
  const before=await page.content(),result=await visibleEvidence(page);
  assert.equal(result.image_exclusion_version,'explicit-empty-alt-rendered-pixel-v2');
  assert.equal(result.visible_images,5);assert.equal(result.broken_images,5);
  assert.equal(await page.content(),before);
 }finally{await browser.close();}
});


test('observed open MediaSource with no buffers remains distinct from stalled buffered media and arbitrary blob URLs',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();await page.evaluate(require('../media_source_observation').observe);
  await page.setContent('<video width="200" height="100" preload="none"><source src="https://example.org/original.m3u8"></video>');
  await page.evaluate(()=>{window.testSource=new MediaSource();document.querySelector('video').src=URL.createObjectURL(testSource);});
  await page.waitForFunction(()=>testSource.readyState==='open');
  const pending=await visibleEvidence(page);assert.equal(pending.unbuffered_media,1);assert.equal(pending.broken_media,0);assert.equal(pending.media_descriptors[0].media_source.buffers,0);
  await page.evaluate(()=>testSource.addSourceBuffer('video/webm; codecs="vp8"'));
  const stalled=await visibleEvidence(page);assert.equal(stalled.unbuffered_media,0);assert.equal(stalled.broken_media,1);
 }finally{await browser.close();}
});
test('captured browser-created nested links retain topology and labels after serialization',async()=>{
 const fs=require('node:fs'),path=require('node:path');const helper=fs.readFileSync(path.join(__dirname,'../../web/app/frozen_nested_links.js'),'utf8');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();await page.setContent('<main></main>');
  await page.evaluate(()=>{const outer=document.createElement('a'),inner=document.createElement('a'),headline=document.createElement('span');outer.href='https://example.test/card';inner.href='https://example.test/brand';inner.rel='nofollow noopener';inner.target='_blank';inner.innerHTML='<span>AD</span><span>Brand</span>';headline.textContent='Card headline';outer.append(inner,headline);document.querySelector('main').append(outer);});
  const before=await visibleEvidence(page);assert.equal(before.controls.length,2);
  const attrs=JSON.stringify({href:'https://example.test/brand',rel:'nofollow noopener',target:'_blank'}).replace(/"/g,'&quot;');
  await page.setContent('<html><head><script>'+helper+'</script></head><body><main><a href="https://example.test/card"><span data-warp-frozen-nested-anchor="'+attrs+'"><span>AD</span><span>Brand</span></span><span>Card headline</span></a></main></body></html>');
  const after=await visibleEvidence(page);assert.deepEqual(after.controls,before.controls);assert.equal(after.control_label_version,'visible-text-nodes-v1');
  assert.deepEqual(await page.locator('a > a').evaluate(e=>[e.href,e.rel,e.target]),['https://example.test/brand','nofollow noopener','_blank']);
  await page.evaluate(helper);assert.equal(await page.locator('a').count(),2);
 }finally{await browser.close();}
});

test('native media objects are observed without inventing URLs, buffers or a loaded frame',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();await page.setContent('<video style="width:200px;height:100px"></video>');await page.locator('video').evaluate(e=>{e.srcObject=new MediaStream();});
  const state=(await visibleEvidence(page)).media_descriptors[0];assert.equal(state.media_object_observation_version,'observed-media-object-v1');assert.equal(state.src_object_kind,'MediaStream');assert.equal(state.current_src,'');assert.deepEqual(state.buffered_ranges,[]);assert.equal(state.video_width,0);assert.equal(state.video_height,0);assert.notEqual(state.state,'loaded');
 }finally{await browser.close();}
});
