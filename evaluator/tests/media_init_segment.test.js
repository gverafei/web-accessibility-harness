'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const init=require('../media_init_segment');
function box(type,body=Buffer.alloc(0)){const b=Buffer.alloc(8+body.length);b.writeUInt32BE(b.length);b.write(type,4);body.copy(b,8);return b;}
function element(id,body){assert.ok(body.length<127);return Buffer.concat([Buffer.from(id,'hex'),Buffer.from([128|body.length]),body]);}
function webm(){const header=element('1a45dfa3',element('4282',Buffer.from('webm')));const seek=element('114d9b74',element('4dbb',element('53ab',Buffer.from('1f43b675','hex'))));const info=element('1549a966',Buffer.alloc(0)),tracks=element('1654ae6b',Buffer.alloc(0)),cluster=element('1f43b675',Buffer.from([1,2,3]));return{header,seek,info,tracks,cluster,bytes:Buffer.concat([header,Buffer.from('18538067ff','hex'),seek,info,tracks,cluster])};}
test('copies only complete observed MP4 initialization and records exact prefix checksum',()=>{
 const prefix=Buffer.concat([box('ftyp',Buffer.from('isom0000')),box('moov',box('free'))]),input=Buffer.concat([prefix,box('moof'),box('mdat',Buffer.from('frames'))]);const before=Buffer.from(input),r=init.extract(input,'video/mp4');assert.deepEqual(r.body,prefix);assert.equal(r.sha256,crypto.createHash('sha256').update(prefix).digest('hex'));assert.equal(r.byte_length,prefix.length);assert.deepEqual(input,before);r.body[0]=255;assert.deepEqual(input,before);
});
test('rejects incomplete, reordered, unsupported and over-bound MP4 evidence',()=>{
 for(const b of [box('moov'),Buffer.concat([box('ftyp',Buffer.from('isom0000')),Buffer.from('000001006d6f6f76','hex')]),Buffer.concat([box('ftyp',Buffer.from('isom0000')),box('xxxx'),box('moov')]),Buffer.alloc(init.MAX_BYTES+1)])assert.throws(()=>init.extract(b,'video/mp4'));
 assert.throws(()=>init.extract(Buffer.alloc(8),'video/unknown'));
});
test('follows WebM hierarchy instead of mistaking a SeekID for the first Cluster',()=>{
 const w=webm(),r=init.extract(w.bytes,'video/webm'),marker=w.bytes.indexOf(Buffer.from('1f43b675','hex'));assert.ok(r.byte_length>marker);assert.deepEqual(r.body,w.bytes.subarray(0,w.bytes.length-w.cluster.length));assert.deepEqual(init.extract(r.body,'video/webm').body,r.body);
});
test('rejects missing WebM tracks, wrong DocType, unknown child sizes and truncated parents',()=>{
 const w=webm();for(const b of [Buffer.concat([w.header,Buffer.from('18538067ff','hex'),w.info,w.cluster]),Buffer.concat([element('1a45dfa3',element('4282',Buffer.from('matroska'))),Buffer.from('18538067ff','hex'),w.info,w.tracks,w.cluster]),Buffer.concat([w.header,Buffer.from('18538067ff1549a966ff','hex')]),w.bytes.subarray(0,w.header.length-1)])assert.throws(()=>init.extract(b,'video/webm'));
});
test('actual WebM prefix restores real Worker MediaSourceHandle metadata without frames or HTML changes',async()=>{
 const {chromium}=require('playwright'),b=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});try{
  const p=await b.newPage();await p.route('https://metadata.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><video muted controls></video></body></html>'}));await p.goto('https://metadata.example/');
  const bytes=Buffer.from(await p.evaluate(async()=>{const c=document.createElement('canvas');c.width=32;c.height=32;const x=c.getContext('2d');x.fillStyle='green';x.fillRect(0,0,32,32);const stream=c.captureStream(10),rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),parts=[];rec.ondataavailable=e=>parts.push(e.data);const done=new Promise(resolve=>rec.onstop=resolve);rec.start();await new Promise(resolve=>setTimeout(resolve,350));rec.stop();await done;stream.getTracks().forEach(t=>t.stop());return [...new Uint8Array(await new Blob(parts).arrayBuffer())];}));
  const prefix=init.extract(bytes,'video/webm');assert.ok(prefix.byte_length<bytes.length);const before=await p.content();
  await p.route('https://metadata.example/worker.js',r=>r.fulfill({contentType:'application/javascript',body:'const source=new MediaSource(),handle=source.handle;postMessage({handle},[handle]);source.addEventListener("sourceopen",()=>{const buffer=source.addSourceBuffer("video/webm;codecs=vp8");onmessage=e=>buffer.appendBuffer(Uint8Array.from(e.data));buffer.onupdateend=()=>postMessage({updated:true});});'}));
  await p.evaluate(async bytes=>{const video=document.querySelector('video'),worker=new Worker('/worker.js');window.metadataWorker=worker;await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Worker init deadline')),5000);worker.onmessage=e=>{if(e.data.handle){video.srcObject=e.data.handle;setTimeout(()=>worker.postMessage(bytes),100);}if(e.data.updated){clearTimeout(timer);resolve();}};});},[...prefix.body]);
  await p.waitForFunction(()=>document.querySelector('video').readyState===1);const state=await p.locator('video').evaluate(e=>({kind:e.srcObject.constructor.name,ready:e.readyState,width:e.videoWidth,height:e.videoHeight,buffered:e.buffered.length,time:e.currentTime,error:e.error?.code||null}));assert.deepEqual(state,{kind:'MediaSourceHandle',ready:1,width:32,height:32,buffered:0,time:0,error:null});assert.equal(await p.content(),before);
 }finally{await b.close();}
});
