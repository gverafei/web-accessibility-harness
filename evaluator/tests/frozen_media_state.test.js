const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),{restore}=require('../frozen_media_state'),{visibleEvidence}=require('../replay_admission');
function wave(){const samples=24000,body=Buffer.alloc(44+samples*2);body.write('RIFF');body.writeUInt32LE(body.length-8,4);body.write('WAVEfmt ',8);body.writeUInt32LE(16,16);body.writeUInt16LE(1,20);body.writeUInt16LE(1,22);body.writeUInt32LE(8000,24);body.writeUInt32LE(16000,28);body.writeUInt16LE(2,32);body.writeUInt16LE(16,34);body.write('data',36);body.writeUInt32LE(samples*2,40);return body;}
test('observed paused direct media restores actual frozen bytes and frame, preserves authored HTML',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();let requests=0;const url='https://media.example/sound.wav';
  await page.route(url,async route=>{requests++;const reply=require('../frozen_media').response({mime:'audio/wav',body:wave(),headers:{}},route.request().headers().range);await route.fulfill({status:reply.status,headers:reply.headers,body:reply.body});});
  const html='<html><body><audio controls preload="none" src="'+url+'"></audio></body></html>';
  await page.setContent(html);await page.locator('audio').evaluate(async e=>{e.muted=true;await e.play();e.pause();});
  await page.waitForFunction(()=>document.querySelector('audio').readyState>=2);
  await page.locator('audio').evaluate(e=>{e.preload='none';e.pause();e.currentTime=0.5;});await page.waitForFunction(()=>!document.querySelector('audio').seeking&&document.querySelector('audio').currentTime===0.5);
  const reference=(await visibleEvidence(page)).media_descriptors;
  assert.equal(reference[0].current_time,0.5);assert.equal(reference[0].position_version,'observed-media-position-v1');
  await page.setContent(html);const before=await page.content();
  const stored=reference.map(r=>({...r,identity:{kind:r.identity.kind,poster:r.identity.poster,preload:r.identity.preload,sources:r.identity.sources}}));
  const result=await restore(page,stored,[url]);assert.equal(result.results[0].status,'restored');assert.equal(result.results[0].time,0.5);assert.equal(await page.content(),before);assert.ok(requests>=2);const settledRequests=requests;
  const after=await visibleEvidence(page);assert.equal(after.broken_media,0);assert.equal(after.media_descriptors[0].paused,true);
  assert.equal((await restore(page,reference,[url])).results[0].status,'restored');assert.equal(requests,settledRequests);
  await page.setContent(html);assert.equal((await restore(page,reference,[])).eligible,0);assert.equal(requests,settledRequests);
  assert.equal((await restore(page,reference.map(r=>({...r,position_version:undefined})),[url])).eligible,0);
  assert.equal((await restore(page,reference.map(r=>({...r,state:'deferred'})),[url])).eligible,0);
  assert.equal((await restore(page,reference.map(r=>({...r,media_source:{buffers:1}})),[url])).eligible,0);
  assert.equal((await restore(page,reference.map(r=>({...r,current_time:NaN})),[url])).eligible,0);
  assert.equal((await restore(page,reference.map(r=>({...r,position_path:'body *'})),[url])).eligible,0);
  await page.setContent(html.replace('preload="none"','preload="metadata"'));assert.equal((await restore(page,reference,[url])).results[0].status,'unmatched_reference');
 }finally{await browser.close();}
});
test('broken frozen media stays failed rather than pretending frame restoration',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage(),url='https://media.example/broken.wav';await page.route(url,r=>r.fulfill({contentType:'audio/wav',body:'invalid'}));await page.setContent('<audio controls preload="none" src="'+url+'"></audio>');
  const r={position_version:'observed-media-position-v1',position_path:'html > body:nth-of-type(1) > audio:nth-of-type(1)',state:'loaded',ready_state:4,paused:true,current_time:0,current_src:url,media_source:null,identity:{kind:'AUDIO',preload:'none',poster:'',sources:[url]}};
  const result=await restore(page,[r],[url]);assert.equal(result.results[0].status,'failed');assert.equal(await page.locator('audio').getAttribute('preload'),'none');assert.equal((await visibleEvidence(page)).broken_media,1);
 }finally{await browser.close();}
});
test('multiple slow frozen media loads restore concurrently inside the unchanged common deadline',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage(),urls=['https://media.example/first.wav','https://media.example/second.wav'];let active=0,maxActive=0;
  await page.route('https://media.example/*.wav',async route=>{active++;maxActive=Math.max(maxActive,active);await new Promise(r=>setTimeout(r,8000));const reply=require('../frozen_media').response({mime:'audio/wav',body:wave(),headers:{}},route.request().headers().range);await route.fulfill({status:reply.status,headers:reply.headers,body:reply.body});active--;});
  await page.setContent('<html><body>'+urls.map(u=>'<audio controls preload="none" src="'+u+'"></audio>').join('')+'</body></html>');
  const html=await page.content(),reference=urls.map((url,i)=>({position_version:'observed-media-position-v1',position_path:'html > body:nth-of-type(1) > audio:nth-of-type('+(i+1)+')',state:'loaded',ready_state:4,paused:true,current_time:0.5,current_src:url,media_source:null,identity:{kind:'AUDIO',preload:'none',poster:'',sources:[url]}}));
  const result=await restore(page,reference,urls);assert.equal(result.budget_ms,15000);assert.ok(maxActive>=2);assert.deepEqual(result.results.map(r=>r.status),['restored','restored']);assert.deepEqual(result.results.map(r=>r.time),[0.5,0.5]);assert.equal(await page.content(),html);assert.equal((await visibleEvidence(page)).broken_media,0);
  await assert.rejects(()=>restore(page,[reference[0],reference[0]],urls),/Ambiguous/);
 }finally{await browser.close();}
});

test('media fragment identity remains intact while decoder uses its fragment-free HTTP bytes',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage(),http='https://media.example/fragment.wav',src=http+'#t=0.5';
  await page.route(http,async route=>{const reply=require('../frozen_media').response({mime:'audio/wav',body:wave(),headers:{}},route.request().headers().range);await route.fulfill(reply);});
  const html='<audio controls preload="none" src="'+src+'"></audio>';await page.setContent(html);await page.locator('audio').evaluate(async e=>{e.muted=true;await e.play();e.pause();});await page.waitForFunction(()=>document.querySelector('audio').readyState>=2);
  const reference=(await visibleEvidence(page)).media_descriptors;await page.setContent(html);const before=await page.content();const result=await restore(page,reference,[http]);assert.equal(result.eligible,1);assert.equal(result.results[0].status,'restored');assert.equal(await page.content(),before);assert.equal(await page.locator('audio').getAttribute('src'),src);
 }finally{await browser.close();}
});
