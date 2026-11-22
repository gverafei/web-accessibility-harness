const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),mse=require('../observed_mse_buffers');
async function browser(){return chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});}
async function makeClip(page){return page.evaluate(async()=>{
 const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;const ctx=canvas.getContext('2d');ctx.fillStyle='green';ctx.fillRect(0,0,32,32);
 const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),chunks=[];
 recorder.ondataavailable=e=>chunks.push(e.data);const stopped=new Promise(resolve=>recorder.onstop=resolve);recorder.start();
 await new Promise(resolve=>setTimeout(resolve,350));ctx.fillStyle='blue';ctx.fillRect(0,0,32,32);await new Promise(resolve=>setTimeout(resolve,350));recorder.stop();await stopped;stream.getTracks().forEach(t=>t.stop());
 const bytes=new Uint8Array(await new Blob(chunks).arrayBuffer());return [...bytes];
});}
async function load(page,bytes){await page.evaluate(async bytes=>{
 const video=document.createElement('video');video.muted=true;document.body.append(video);
 const source=new MediaSource();video.src=URL.createObjectURL(source);await new Promise(resolve=>source.addEventListener('sourceopen',resolve,{once:true}));
 const buffer=source.addSourceBuffer('video/webm; codecs="vp8"'),done=new Promise(resolve=>buffer.addEventListener('updateend',resolve,{once:true}));
 const array=new Uint8Array(bytes.length+10);array.set(bytes,5);buffer.appendBuffer(array.subarray(5,5+bytes.length));await done;source.endOfStream();
 await video.play();video.pause();window.testSource=source;window.testBuffer=buffer;
},bytes);await page.waitForFunction(()=>document.querySelector('video').readyState>=2);}
test('records actual native MSE append view bytes, codec, state and verified hashes without changing DOM',async()=>{
 const b=await browser();try{const page=await b.newPage();await mse.install(page);await page.goto('about:blank');const bytes=await makeClip(page);await load(page,bytes);const before=await page.content();
 await page.evaluate(()=>URL.createObjectURL(testSource));
 const captured=await mse.capture(page);assert.equal(captured.records.length,1);assert.equal(captured.records[0].aliases.length,2);assert.equal(captured.total_bytes,bytes.length);const r=captured.records[0];assert.deepEqual(r.reasons,[]);assert.equal(r.ready_state,'ended');assert.equal(mse.validate(r),bytes.length);assert.deepEqual([...Buffer.from(r.buffers[0].appends[0].body,'base64')],bytes);assert.equal(await page.content(),before);
 const tampered=structuredClone(r);tampered.buffers[0].appends[0].sha256='0'.repeat(64);assert.throws(()=>mse.validate(tampered),/checksum/);
 await page.evaluate(()=>testBuffer.remove(0,0.1));const removed=(await mse.capture(page)).records[0];assert.ok(removed.reasons.includes('unsupported_remove'));assert.throws(()=>mse.validate(removed),/Incomplete/);
 }finally{await b.close();}
});
test('byte limit never prevents native decoding and refuses an incomplete recording',async()=>{
 const b=await browser();try{const page=await b.newPage();await mse.install(page,{maxBytes:1});await page.goto('about:blank');const bytes=await makeClip(page);await load(page,bytes);const capture=await mse.capture(page);
 assert.equal(capture.total_bytes,0);assert.deepEqual(capture.records[0].reasons,['byte_limit']);assert.throws(()=>mse.validate(capture.records[0]),/Incomplete/);
 await assert.rejects(mse.install(page,{maxBytes:mse.MAX_BYTES+1}),/Invalid/);
 }finally{await b.close();}
});

test('reconstructs a decoded paused MSE frame from the exact recorded bytes without network',async()=>{
 const b=await browser();try{const original=await b.newPage();await mse.install(original);await original.goto('about:blank');const bytes=await makeClip(original);await load(original,bytes);const r=(await mse.capture(original)).records[0];
 const replay=await b.newPage();let requests=0;await replay.route('**/*',route=>{requests++;return route.abort();});await replay.setContent('<video preload="none" src="blob:https://original.example/old"></video>');
 const restored=await mse.restore(replay,'html > body:nth-of-type(1) > video:nth-of-type(1)',r,0);
 assert.equal(restored.status,'restored');assert.ok(restored.ready_state>=2);assert.equal(restored.video_width,32);assert.equal(restored.video_height,32);assert.equal(restored.current_time,0);assert.equal(restored.live_resources,false);assert.equal(requests,0);assert.equal(await replay.locator('video').getAttribute('preload'),'none');
 assert.equal(restored.original_src,'blob:https://original.example/old');assert.notEqual(restored.current_src,restored.original_src);
 const pixel=page=>page.locator('video').evaluate(video=>{const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;const ctx=canvas.getContext('2d');ctx.drawImage(video,0,0);return [...ctx.getImageData(16,16,1,1).data];});
 await original.locator('video').evaluate(v=>{v.currentTime=0;});await original.waitForFunction(()=>!document.querySelector('video').seeking);assert.deepEqual(await pixel(replay),await pixel(original));
 assert.equal((await mse.restore(replay,'html > body:nth-of-type(1) > audio:nth-of-type(1)',r,0)).status,'unmatched_reference');
 await assert.rejects(mse.restore(replay,'body *',r,0),/Invalid/);
 const unavailable=await mse.restore(replay,'html > body:nth-of-type(1) > video:nth-of-type(1)',r,100,{budgetMs:200});assert.equal(unavailable.status,'failed');
 const invalid=structuredClone(r);invalid.buffers[0].codec='video/x-unavailable';assert.equal((await mse.restore(replay,'html > body:nth-of-type(1) > video:nth-of-type(1)',invalid,0)).status,'unsupported_codec');
 }finally{await b.close();}
});

test('native append exceptions are preserved and do not create observed bytes',async()=>{
 const b=await browser();try{const page=await b.newPage();await mse.install(page);await page.goto('about:blank');const bytes=await makeClip(page);await load(page,bytes);
 const before=await mse.capture(page),exception=await page.evaluate(()=>{try{testBuffer.appendBuffer(null);return null;}catch(error){return error.name;}});
 assert.equal(exception,'TypeError');assert.equal((await mse.capture(page)).total_bytes,before.total_bytes);
 }finally{await b.close();}
});

test('native MSE reference associates exact element and refuses changed identity, foreign origin and ambiguous sources',async()=>{
 const b=await browser();try{
 const page=await b.newPage();await mse.install(page);await require('../media_source_observation').install(page);await page.route('https://mse.example/',route=>route.fulfill({body:'<html><body></body></html>',contentType:'text/html'}));await page.goto('https://mse.example/');const bytes=await makeClip(page);await load(page,bytes);
 const visible=await require('../replay_admission').visibleEvidence(page),bundle=await mse.reference(page,visible);assert.equal(bundle.records.length,1);assert.equal(bundle.targets.length,1);assert.equal(mse.verifyBundle(bundle,'https://mse.example/'),bytes.length);
 const html=await page.content();await page.setContent(html);const restored=await mse.restoreReference(page,bundle,'https://mse.example/');assert.equal(restored.results[0].status,'restored');assert.equal(restored.results[0].video_width,32);
 await page.setContent(html.replace('muted=""',''));await page.locator('video').evaluate(e=>e.preload='none');assert.equal((await mse.restoreReference(page,bundle,'https://mse.example/')).results[0].status,'unmatched_reference');
 assert.throws(()=>mse.verifyBundle(bundle,'https://other.example/'),/foreign/);
 const duplicate=structuredClone(bundle);duplicate.records.push(duplicate.records[0]);assert.throws(()=>mse.verifyBundle(duplicate),/Ambiguous/);
 const wrongSize=structuredClone(bundle);wrongSize.total_bytes++;assert.throws(()=>mse.verifyBundle(wrongSize),/aggregate/);
 await page.setContent('<html><body></body></html>');assert.equal((await mse.restoreReference(page,bundle,'https://mse.example/')).results[0].status,'unmatched_reference');
 }finally{await b.close();}
});

test('native acquisition to origin snapshot preserves a real loaded MSE frame with shared accounting',async()=>{
 const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');const root=fs.mkdtempSync('/results/mse-integration-');
 const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 const b=await browser();try{
 const page=await b.newPage({viewport:{width:1440,height:1000}});await mse.install(page);await require('../media_source_observation').install(page);await require('../measurement_state').install(page);
 await page.route('https://mse.example/',route=>route.fulfill({body:'<html lang="en"><head><title>MSE test</title></head><body><p>Native page</p></body></html>',contentType:'text/html'}));const collector=require('../native_resources').collect(page);await collector.ready;
 await page.goto('https://mse.example/');const bytes=await makeClip(page);await load(page,bytes);
 const ref=await require('../native_reference').capture(page,collector,path.join(root,'native.jpg'));
 assert.equal(ref.version,'native-reference-state-v12');assert.equal(ref.mse_buffer_reference.total_bytes,bytes.length);assert.equal(ref.mse_buffer_reference.targets.length,1);
 const input=path.join(root,'input.json');fs.writeFileSync(input,JSON.stringify({version:require('../origin_snapshot').VERSION,origin:page.url(),document:ref.html,assets:[],media_reference:ref.visible.media_descriptors,mse_buffer_reference:ref.mse_buffer_reference}));
 const audited=await require('../origin_snapshot').run(input,path.join(root,'replay'),false);assert.equal(audited.status,'completed');assert.equal(audited.transport.phase_evidence.stable,true);assert.ok(Number.isFinite(audited.axe.wcag_violations));assert.ok(Number.isFinite(audited.lighthouse.accessibility_score));const replay={...audited.transport,...audited.transport.visible};
 assert.equal(replay.mse_restoration.results[0].status,'restored');assert.equal(replay.broken_media,0);assert.equal(replay.visible_media,1);assert.equal(replay.live_network,false);
 assert.ok(Math.abs(replay.media_descriptors[0].current_time-ref.visible.media_descriptors[0].current_time)<=0.01);assert.equal(replay.media_descriptors[0].video_width,32);
 const corrupt=JSON.parse(fs.readFileSync(input));corrupt.mse_buffer_reference.records[0].buffers[0].appends[0].sha256='0'.repeat(64);fs.writeFileSync(input,JSON.stringify(corrupt));assert.throws(()=>require('../origin_snapshot').readManifest(input),/checksum/);
 }finally{evidence.publicUrl=old;await b.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('all audio/video SourceBuffers exist before decoding either track',async()=>{
 const b=await browser();try{
 const page=await b.newPage();await mse.install(page);await page.goto('about:blank');await page.mouse.click(50,50);const videoBytes=await makeClip(page);
 const audioBytes=await page.evaluate(async()=>{
  const context=new AudioContext();await context.resume();const oscillator=context.createOscillator(),sink=context.createMediaStreamDestination();oscillator.connect(sink);oscillator.start();
  const recorder=new MediaRecorder(sink.stream,{mimeType:'audio/webm;codecs=opus'}),chunks=[];recorder.ondataavailable=e=>chunks.push(e.data);const stop=new Promise(resolve=>recorder.onstop=resolve);recorder.start();await new Promise(resolve=>setTimeout(resolve,700));recorder.stop();await stop;oscillator.stop();await context.close();return [...new Uint8Array(await new Blob(chunks).arrayBuffer())];
 });
 await page.evaluate(async({audioBytes,videoBytes})=>{
  const video=document.createElement('video');video.muted=true;document.body.append(video);const source=new MediaSource();video.src=URL.createObjectURL(source);await new Promise(resolve=>source.addEventListener('sourceopen',resolve,{once:true}));
  const buffers=[source.addSourceBuffer('audio/webm;codecs="opus"'),source.addSourceBuffer('video/webm;codecs="vp8"')];
  for(let i=0;i<2;i++){const done=new Promise(resolve=>buffers[i].addEventListener('updateend',resolve,{once:true}));buffers[i].appendBuffer(new Uint8Array([audioBytes,videoBytes][i]));await done;}source.endOfStream();await video.play();video.pause();
 },{audioBytes,videoBytes});
 const record=(await mse.capture(page)).records[0];assert.equal(record.buffers.length,2);const target=await b.newPage();await target.setContent('<video></video>');const restored=await mse.restore(target,'html > body:nth-of-type(1) > video:nth-of-type(1)',record,0.1);assert.equal(restored.status,'restored');assert.equal(restored.video_width,32);assert.ok(restored.ready_state>=2);
 }finally{await b.close();}
});
