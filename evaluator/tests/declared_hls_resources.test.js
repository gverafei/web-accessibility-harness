'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {references,complete}=require('../declared_hls_resources');
const asset=(url,text)=>({url,mime:'application/vnd.apple.mpegurl',body:Buffer.from(text).toString('base64')});
test('HLS freezes all declared renditions, audio, init and bounded initial playback window without duplicate requests',async()=>{
 const root='https://example.org/master.m3u8',assets=[asset(root,'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=100\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=200\nhigh.m3u8')],calls=[],checked=[];
 const fetch=async url=>{calls.push(url);return {status:200,headers:{'content-type':url.endsWith('.m3u8')?'application/vnd.apple.mpegurl':'video/mp2t'},body:Buffer.from(url.endsWith('.m3u8')?'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:15\na.ts\n#EXTINF:15\nb.ts\n#EXTINF:15\nc.ts':'bytes')};};
 const attempts=new Set(),errors=[];await complete(assets,errors,fetch,async u=>checked.push(u),attempts);await complete(assets,errors,fetch,async u=>checked.push(u),attempts);
 assert.deepEqual(calls.map(u=>u.split('/').at(-1)),['audio.m3u8','low.m3u8','high.m3u8','init.mp4','a.ts','b.ts']);assert.deepEqual(checked,calls);assert.equal(errors.length,0);assert.equal(assets.length,7);
 assert.ok(assets.slice(1).every(a=>a.sha256&&a.declared_capture.version==='declared-hls-resources-v6'));
});
test('HLS refuses unproven encryption, byte ranges and non HTTP declarations',()=>{
 for(const text of ['#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\na.ts','#EXTM3U\n#EXT-X-BYTERANGE:20@0\na.ts','#EXTM3U\nfile:///private'])assert.throws(()=>references(text,'https://example.org/m.m3u8'));
});
test('HLS validates every redirect, refuses error bodies and never retries failed URLs',async()=>{
 const assets=[asset('https://example.org/master.m3u8','#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nchild.m3u8')],errors=[],attempts=new Set(),checked=[],calls=[];
 const fetch=async url=>{calls.push(url);return url.endsWith('child.m3u8')?{status:302,headers:{location:'https://cdn.example.org/final.m3u8'},body:Buffer.alloc(0)}:{status:200,headers:{'content-type':'text/html'},body:Buffer.from('error')};};
 await complete(assets,errors,fetch,async u=>checked.push(u),attempts);await complete(assets,errors,fetch,async u=>checked.push(u),attempts);
 assert.equal(calls.length,2);assert.deepEqual(checked,calls);assert.equal(errors.length,1);assert.equal(assets.length,1);
});

test('HLS includes the full initial 30 second window and caps tiny segments at eight',()=>{
 assert.deepEqual(references('#EXTM3U\n#EXTINF:7,\na.ts\n#EXTINF:7,\nb.ts\n#EXTINF:4,\nc.ts','https://example.org/m.m3u8').map(u=>u.split('/').at(-1)),['a.ts','b.ts','c.ts']);
 assert.equal(references('#EXTM3U\n'+Array.from({length:20},(_,i)=>'#EXTINF:1,\n'+i+'.ts').join('\n'),'https://example.org/m.m3u8').length,8);
});
test('HLS shares the forty HTTP request budget across collector finishes and redirects',async()=>{
 const master=n=>asset('https://example.org/master'+n+'.m3u8','#EXTM3U\n'+Array.from({length:30},(_,i)=>'#EXT-X-STREAM-INF:BANDWIDTH=1\n'+n+'-'+i+'.m3u8').join('\n'));
 const assets=[master(1)],errors=[],attempts=new Set();let calls=0;
 const fetch=async()=>{calls++;return {status:200,headers:{'content-type':'application/vnd.apple.mpegurl'},body:Buffer.from('#EXTM3U\n#EXT-X-ENDLIST')};};
 await complete(assets,errors,fetch,async()=>{},attempts);assets.push(master(2));await complete(assets,errors,fetch,async()=>{},attempts);await complete(assets,errors,fetch,async()=>{},attempts);
 assert.equal(calls,40);assert.ok(errors.some(e=>e.kind==='declared_hls_limit'));
});


test('HLS gives every declared rendition its first segment before using remaining budget on later segments',async()=>{
 const roots=Array.from({length:3},(_,i)=>asset(`https://example.org/root${i}.m3u8`,'#EXTM3U\n'+Array.from({length:5},(_,j)=>`#EXT-X-STREAM-INF:BANDWIDTH=1\n${i}-${j}.m3u8`).join('\n'))),calls=[],errors=[];
 const fetch=async url=>{calls.push(url);const leaf=url.split('/').at(-1);return {status:200,headers:{'content-type':url.endsWith('.m3u8')?'application/vnd.apple.mpegurl':'video/mp2t'},body:Buffer.from(url.endsWith('.m3u8')?'#EXTM3U\n'+Array.from({length:8},(_,k)=>`#EXTINF:4,\n${leaf}-${k}.ts`).join('\n'):'real recorded bytes')};};
 await complete(roots,errors,fetch,async()=>{});
 assert.equal(calls.length,40);
 const segments=calls.filter(url=>url.endsWith('.ts'));
 assert.equal(segments.length,25);
 assert.ok(segments.slice(0,15).every(url=>url.endsWith('-0.ts')));
 assert.equal(new Set(segments.slice(0,15)).size,15);
 assert.ok(errors.some(error=>error.kind==='declared_hls_limit'));
});


test('an empty collector finish does not spend the HLS recovery clock before a player declares a playlist',async()=>{
 const originalNow=Date.now;let clock=1000;Date.now=()=>clock;
 try{
  const assets=[],errors=[],attempted=new Set();let calls=0;
  const fetch=async()=>{calls++;return {status:200,headers:{'content-type':'video/mp2t'},body:Buffer.from('recorded segment')};};
  await complete(assets,errors,fetch,async()=>{},attempted);
  clock+=60000;assets.push(asset('https://example.org/later.m3u8','#EXTM3U\n#EXTINF:5,\nfirst.ts'));
  await complete(assets,errors,fetch,async()=>{},attempted);
  assert.equal(calls,1);assert.equal(errors.length,0);
  clock+=46000;assets.push(asset('https://example.org/too-late.m3u8','#EXTM3U\n#EXTINF:5,\nlater.ts'));
  await complete(assets,errors,fetch,async()=>{},attempted);
  assert.equal(calls,2);assert.ok(!errors.some(error=>error.kind==='declared_hls_limit'));
 }finally{Date.now=originalNow;}
});


test('native consumed playlists get observed-frame bytes before optional renditions exhaust the budget',async()=>{
 const master=asset('https://example.org/root.m3u8','#EXTM3U\n'+Array.from({length:50},(_,i)=>'#EXT-X-STREAM-INF:BANDWIDTH=1\nunused'+i+'.m3u8').join('\n'));
 const used={...asset('https://example.org/used.m3u8','#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\nused0.ts\n#EXTINF:6,\nused1.ts'),native_response_sequence:3,body_representation:{kind:'browser_response_entity'}};
 const calls=[],errors=[],assets=[master,used];const fetch=async url=>{calls.push(url);return {status:200,headers:{'content-type':url.endsWith('.m3u8')?'application/vnd.apple.mpegurl':'video/mp2t'},body:Buffer.from(url.endsWith('.m3u8')?'#EXTM3U\n#EXT-X-ENDLIST':'genuine bytes')};};
 await complete(assets,errors,fetch,async()=>{},new Set(),undefined,{observedMedia:[{current_time:3}]});
 assert.deepEqual(calls.slice(0,2),['https://example.org/init.mp4','https://example.org/used0.ts']);assert.equal(calls.length,40);assert.ok(!calls.includes('https://example.org/used1.ts'));assert.ok(errors.some(e=>e.kind==='declared_hls_limit'));
});
test('HLS discovery uses the latest native response ordinal rather than body completion or recovery order',async()=>{
 const root='https://example.org/root.m3u8';const old={...asset(root,'#EXTM3U\n#EXTINF:6,\nold.ts'),native_response_sequence:1,body_representation:{kind:'browser_response_entity'}};
 const latest={...asset(root,'#EXTM3U\n#EXTINF:6,\nlatest.ts'),native_response_sequence:2,body_representation:{kind:'browser_response_entity'}};
 const recovery=asset(root,'#EXTM3U\n#EXTINF:6,\nrecovery.ts');const calls=[];
 await complete([latest,old,recovery],[],async url=>{calls.push(url);return {status:200,headers:{'content-type':'video/mp2t'},body:Buffer.from('captured bytes')};},async()=>{});
 assert.deepEqual(calls,['https://example.org/latest.ts']);
});


test('intermediate finishes reserve native resources before optional variants, including a late native rendition',async()=>{
 const root=asset('https://example.org/root.m3u8','#EXTM3U\n'+Array.from({length:50},(_,i)=>'#EXT-X-STREAM-INF:BANDWIDTH=1\noptional'+i+'.m3u8').join('\n'));
 const assets=[root],errors=[],attempted=new Set(),calls=[];const fetch=async url=>{calls.push(url);return {status:200,headers:{'content-type':url.endsWith('.m3u8')?'application/vnd.apple.mpegurl':'video/mp2t'},body:Buffer.from(url.endsWith('.m3u8')?'#EXTM3U\n#EXT-X-ENDLIST':'real bytes')};};
 await complete(assets,errors,fetch,async()=>{},attempted,undefined,{allowOptional:false});assert.equal(calls.length,0);
 const late={...asset('https://example.org/late.m3u8','#EXTM3U\n#EXTINF:6,\nlate0.ts\n#EXTINF:6,\nlate1.ts'),native_response_sequence:100,body_representation:{kind:'browser_response_entity'}};assets.push(late);
 await complete(assets,errors,fetch,async()=>{},attempted,undefined,{allowOptional:false,observedMedia:[{current_time:3}]});assert.deepEqual(calls,['https://example.org/late0.ts']);
 await complete(assets,errors,fetch,async()=>{},attempted,undefined,{allowOptional:true,observedMedia:[{current_time:3}]});assert.equal(calls.length,40);assert.equal(calls.filter(u=>u.endsWith('late0.ts')).length,1);assert.ok(!calls.includes('https://example.org/late1.ts'));assert.ok(errors.some(e=>e.kind==='declared_hls_limit'));
});

test('HLS charges accumulated recovery work but not idle intervals between collector phases',async()=>{
 const originalNow=Date.now;let clock=1000;Date.now=()=>clock;
 try{const attempted=new Set(),assets=[asset('https://example.org/first.m3u8','#EXTM3U\n#EXTINF:5,\nfirst.ts')],errors=[];let calls=0;
  const fetch=async()=>{calls++;clock+=23000;return{status:200,headers:{'content-type':'video/mp2t'},body:Buffer.from('segment')};};
  const first=await complete(assets,errors,fetch,async()=>{},attempted);assert.equal(first.hls_recovery_budget.elapsed_ms,23000);
  clock+=60000;assets.push(asset('https://example.org/second.m3u8','#EXTM3U\n#EXTINF:5,\nsecond.ts'));const second=await complete(assets,errors,fetch,async()=>{},attempted);assert.equal(calls,2);assert.equal(second.hls_recovery_budget.remaining_ms,0);
  clock+=60000;assets.push(asset('https://example.org/third.m3u8','#EXTM3U\n#EXTINF:5,\nthird.ts'));await complete(assets,errors,fetch,async()=>{},attempted);assert.equal(calls,2);assert.ok(errors.some(e=>e.kind==='declared_hls_limit'));
 }finally{Date.now=originalNow;}
});
