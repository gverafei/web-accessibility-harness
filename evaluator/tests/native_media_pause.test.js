'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),pause=require('../native_media_pause');
function wave(){const b=Buffer.alloc(44+48000);b.write('RIFF');b.writeUInt32LE(b.length-8,4);b.write('WAVEfmt ',8);b.writeUInt32LE(16,16);b.writeUInt16LE(1,20);b.writeUInt16LE(1,22);b.writeUInt32LE(8000,24);b.writeUInt32LE(16000,28);b.writeUInt16LE(2,32);b.writeUInt16LE(16,34);b.write('data',36);b.writeUInt32LE(48000,40);return b;}
async function browser(){return chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});}
test('pauses real decoded progression without changing authored HTML or play promises, preserves explicit positions',async()=>{
 const b=await browser();try{
  const p=await b.newPage();await pause.install(p);
  await p.route('https://paused.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><audio controls preload="auto" src="/sound.wav"></audio></body></html>'}));await p.route('https://paused.example/sound.wav',r=>{const reply=require('../frozen_media').response({mime:'audio/wav',body:wave(),headers:{}},r.request().headers().range);return r.fulfill({status:reply.status,headers:reply.headers,body:reply.body});});await p.goto('https://paused.example/');await p.waitForFunction(()=>document.querySelector('audio').readyState>=2);
  const before=await p.content();
  const state=await p.locator('audio').evaluate(async e=>{e.muted=true;e.playbackRate=0.75;e.volume=0.6;window.authoredPlaying=0;e.addEventListener('playing',()=>{window.authoredPlaying++;window.authoredPlayingTime=e.currentTime;});e.currentTime=0.75;await new Promise(resolve=>e.addEventListener('seeked',resolve,{once:true}));const explicitPosition=e.currentTime;const promise=e.play();const nativePromise=promise instanceof Promise;await promise;await new Promise(resolve=>queueMicrotask(resolve));return{nativePromise,explicitPosition,authoredPlayingTime:window.authoredPlayingTime,paused:e.paused,time:e.currentTime,ready:e.readyState,authored:window.authoredPlaying,muted:e.muted,rate:e.playbackRate,volume:e.volume};});
  assert.equal(state.nativePromise,true);assert.equal(state.paused,true);assert.equal(state.explicitPosition,0.75);assert.ok(Math.abs(state.time-state.authoredPlayingTime)<0.01,JSON.stringify(state));assert.ok(state.ready>=2);assert.equal(state.authored,1);assert.equal(state.muted,true);assert.equal(state.rate,0.75);assert.equal(state.volume,0.6);assert.equal(await p.content(),before);
  const observed=await pause.snapshot(p);assert.equal(observed.version,pause.VERSION);assert.equal(observed.events,1);assert.equal(observed.media[0].first_time,state.time);
  await p.waitForTimeout(200);assert.equal(await p.locator('audio').evaluate(e=>e.currentTime),state.time);
 }finally{await b.close();}
});
test('observer survives document replacement and leaves missing/invalid bytes genuinely broken',async()=>{
 const b=await browser();try{
  const p=await b.newPage();await pause.install(p);await p.route('https://paused.example/',r=>r.fulfill({body:'<html><body></body></html>'}));await p.route('https://paused.example/sound.wav',r=>{const reply=require('../frozen_media').response({mime:'audio/wav',body:wave(),headers:{}},r.request().headers().range);return r.fulfill({status:reply.status,headers:reply.headers,body:reply.body});});await p.route('https://paused.example/broken.wav',r=>r.fulfill({contentType:'audio/wav',body:'broken'}));await p.goto('https://paused.example/');
  const html='<html><body><audio controls preload="auto" src="/sound.wav"></audio></body></html>';await pause.write(p,html);await p.waitForFunction(()=>document.querySelector('audio').readyState>=2);const before=await p.content();
  assert.equal(await p.locator('audio').evaluate(async e=>{e.muted=true;await e.play();await new Promise(resolve=>queueMicrotask(resolve));return e.paused;}),true);assert.equal((await pause.snapshot(p)).events,1);assert.equal(await p.content(),before);
  await pause.write(p,html.replace('sound.wav','broken.wav'));await p.waitForFunction(()=>document.querySelector('audio').error);assert.equal((await pause.snapshot(p)).events,0);assert.equal(await p.locator('audio').evaluate(e=>e.readyState),0);
 }finally{await b.close();}
});
test('native paused video retains a genuinely decoded first frame through frozen replay',async()=>{
 const b=await browser();try{
  const p=await b.newPage();await pause.install(p);const origin='https://paused.example/';await p.route(origin,r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}));await p.goto(origin);
  const bytes=Buffer.from(await p.evaluate(async()=>{
   const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;const ctx=canvas.getContext('2d');ctx.fillStyle='green';ctx.fillRect(0,0,32,32);const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),chunks=[];recorder.ondataavailable=e=>chunks.push(e.data);const stopped=new Promise(resolve=>recorder.onstop=resolve);recorder.start();await new Promise(resolve=>setTimeout(resolve,350));ctx.fillStyle='blue';ctx.fillRect(0,0,32,32);await new Promise(resolve=>setTimeout(resolve,350));recorder.stop();await stopped;stream.getTracks().forEach(t=>t.stop());return [...new Uint8Array(await new Blob(chunks).arrayBuffer())];
  }));const url=origin+'clip.webm';await p.route(url,r=>{const reply=require('../frozen_media').response({mime:'video/webm',body:bytes,headers:{}},r.request().headers().range);return r.fulfill({status:reply.status,headers:reply.headers,body:reply.body});});
  const html='<html><body><video muted controls preload="auto" src="'+url+'"></video></body></html>';await pause.write(p,html);await p.locator('video').evaluate(async e=>{await e.play();});await p.waitForFunction(()=>document.querySelector('video').paused&&document.querySelector('video').readyState>=2);
  const pixels=()=>p.locator('video').evaluate(e=>{const c=document.createElement('canvas');c.width=e.videoWidth;c.height=e.videoHeight;const x=c.getContext('2d');x.drawImage(e,0,0);return [...x.getImageData(16,16,1,1).data];});const beforePixels=await pixels();assert.ok(beforePixels[1]>80&&beforePixels[2]<30);
  const reference=(await require('../replay_admission').visibleEvidence(p)).media_descriptors;assert.ok(reference[0].current_time<0.01);assert.equal(reference[0].video_width,32);
  await pause.write(p,html);const authored=await p.content();const replay=await require('../frozen_media_state').restore(p,reference,[url]);assert.equal(replay.results[0].status,'restored');assert.deepEqual(await pixels(),beforePixels);assert.equal(await p.content(),authored);assert.equal(await p.locator('video').evaluate(e=>e.paused),true);
 }finally{await b.close();}
});
