const test=require('node:test'),assert=require('node:assert/strict');
const {urls,complete}=require('../declared_image_resources');
test('declared image recovery recognizes configuration and lazy images, not navigation or APIs',()=>{
 const doc='<img data-src="/lazy.webp"><script>{"itemMediaSrc":"https://cdn.example/card.png?x=1","api":"https://example.test/api","link":"https://example.test/about"}</script>';
 assert.deepEqual(urls(doc,'https://example.test/'),['https://example.test/lazy.webp','https://cdn.example/card.png?x=1']);
});
test('declared image recovery freezes bytes and checked redirects and reuses existing assets',async()=>{
 const assets=[],errors=[],checked=[],calls=[];
 const fetch=async url=>{calls.push(url);return url.endsWith('/image.png')?{status:302,headers:{location:'https://cdn.example/final.png'},body:Buffer.alloc(0)}:{status:200,headers:{'content-type':'image/png','access-control-allow-origin':'*'},body:Buffer.from('image')};};
 const doc='"https://example.test/image.png"';
 await complete(doc,'https://example.test/',assets,errors,fetch,async url=>checked.push(url));
 assert.deepEqual(checked,calls);assert.equal(assets[0].declared_capture.requested_url,'https://example.test/image.png');assert.equal(assets[0].url,'https://cdn.example/final.png');assert.equal(assets[0].sha256.length,64);assert.equal(errors.length,0);
 // A redirect alias is already frozen too; do not fetch it again.
 await complete('"https://cdn.example/final.png"','https://example.test/',assets,errors,fetch,async()=>{});
 assert.equal(calls.length,2);
});
test('recovery rejects non-images, blocked redirect targets and over-budget bodies',async()=>{
 for(const mode of ['html','private','budget']){
  const assets=[],errors=[];
  await complete('"https://example.test/image.png"','https://example.test/',assets,errors,async()=>mode==='private'?{status:302,headers:{location:'http://127.0.0.1/image.png'},body:Buffer.alloc(0)}:{status:200,headers:{'content-type':mode==='html'?'text/html':'image/png'},body:Buffer.alloc(mode==='budget'?8000001:5)},async url=>{if(url.includes('127.0.0.1'))throw Error('Private address');});
  assert.equal(assets.length,0);assert.equal(errors.length,1);
 }
});
test('native declared images use full GET bodies, not the media Range transport',async()=>{
 const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  const requests=[];
  const page={on(){},off(){},url:()=> 'https://example.test/',content:async()=>'<script>{"itemMediaSrc":"https://cdn.example/card.png"}</script>',context:()=>({request:{get:async(url,options)=>{
   requests.push({url,options});return {status:()=>200,headers:()=>({'content-type':'image/png'}),body:async()=>Buffer.from('complete image'),dispose:async()=>{}};
  }}})};
  const collector=require('../native_resources').collect(page);
  const first=await collector.finish({close:false});const second=await collector.finish();
  assert.equal(first.version,'native-resource-package-v4');assert.equal(first.assets.length,1);assert.equal(second.assets.length,1);
  assert.equal(requests.length,1);assert.equal(requests[0].options.headers,undefined);assert.equal(requests[0].options.maxRedirects,0);
 }finally{evidence.publicUrl=old;}
});
test('aggregate resource ceiling stops declared recovery without another GET',async()=>{
 const body=Buffer.alloc(8000000).toString('base64');
 const assets=Array.from({length:8},(_,i)=>({url:'https://cdn.example/'+i+'.png',mime:'image/png',body}));
 const errors=[];let calls=0;
 await complete('"https://cdn.example/new.png"','https://example.test/',assets,errors,async()=>{calls++;throw Error('unexpected fetch');},async()=>{});
 assert.equal(calls,0);assert.equal(assets.length,8);assert.equal(errors[0].kind,'declared_image_limit');
});

test('native selected responsive variants recover after response-count cap without choosing alternatives',async()=>{
 const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  let listener;const requests=[];const selected='https://cdn.example/resize?width=384&format=auto';
  const page={on(name,fn){listener=fn;},off(){},url:()=> 'https://example.test/',content:async()=>'<img srcset="https://cdn.example/resize?width=384&format=auto 384w, https://cdn.example/resize?width=800 800w">',evaluate:async()=>[selected,'data:image/png;base64,eA==','blob:https://example.test/id'],context:()=>({request:{get:async(url,options)=>{
   requests.push({url,options});return {status:()=>200,headers:()=>({'content-type':'image/png'}),body:async()=>Buffer.from('selected native image'),dispose:async()=>{}};
  }}})};
  const collector=require('../native_resources').collect(page);
  for(let i=0;i<1001;i++)listener({url:()=> 'https://example.test/opaque/'+i,request:()=>({method:()=> 'GET'}),status:()=>200,headers:()=>({'content-type':'application/octet-stream'}),body:async()=>{throw Error('Native eligible body unavailable');}});
  const first=await collector.finish({close:false});const second=await collector.finish();
  assert.equal(first.assets.length,1);assert.equal(second.assets.length,1);assert.deepEqual(requests.map(r=>r.url),[selected]);assert.equal(requests[0].options.headers,undefined);
  assert.equal(first.assets[0].declared_capture.version,'declared-image-resources-v3');assert.equal(first.errors.filter(e=>e.reason==='resource response count limit').length,1);
 }finally{evidence.publicUrl=old;}
});
test('browser and declared recovery share one aggregate byte reservation across awaits',async()=>{
 const evidence=require('../harness_evidence'),limits=require('../evidence_limits'),old=evidence.publicUrl,ceiling=limits.TOTAL_RESOURCE_BYTES;evidence.publicUrl=async()=>{};limits.TOTAL_RESOURCE_BYTES=20;
 try{
  let listener;const reply=url=>({url:()=>url,request:()=>({method:()=> 'GET',redirectedFrom:()=>null}),status:()=>200,headers:()=>({'content-type':'image/png'}),body:async()=>Buffer.alloc(8)});
  const page={on(n,fn){listener=fn;},off(){},url:()=> 'https://example.test/',content:async()=>'<img src="https://cdn.example/selected.png">',context:()=>({request:{get:async()=>{
   listener(reply('https://cdn.example/late.png'));await new Promise(r=>setImmediate(r));return {status:()=>200,headers:()=>({'content-type':'image/png'}),body:async()=>Buffer.alloc(8),dispose:async()=>{}};
  }}})};
  const collector=require('../native_resources').collect(page);listener(reply('https://cdn.example/first.png'));
  const result=await collector.finish();assert.equal(result.assets.reduce((n,a)=>n+Buffer.from(a.body,'base64').length,0),16);assert.equal(result.assets.length,2);assert.ok(result.errors.some(e=>e.reason==='resource capture budget'));
 }finally{evidence.publicUrl=old;limits.TOTAL_RESOURCE_BYTES=ceiling;}
});
test('loaded browser-selected media recovers beyond response cap and validates actual MIME',async()=>{
 const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  for(const mime of ['video/mp4','text/html']){
   const url='https://cdn.example/observed-video';let calls=0;
   const page={on(){},off(){},url:()=> 'https://example.test/',content:async()=>'',evaluate:async fn=>String(fn).includes('video,audio')?[{url,mime:'video/unknown',observed_kind:'VIDEO'}]:[],context:()=>({request:{get:async()=>{
    calls++;return {status:()=>200,headers:()=>({'content-type':mime}),body:async()=>Buffer.from('real recorded bytes'),dispose:async()=>{}};
   }}})};
   const collector=require('../native_resources').collect(page);const first=await collector.finish({close:false});const second=await collector.finish();
   assert.equal(calls,1);assert.equal(first.assets.length,mime==='video/mp4'?1:0);assert.equal(second.assets.length,first.assets.length);
   if(mime==='video/mp4'){assert.equal(first.assets[0].mime,mime);assert.equal(first.assets[0].media_capture.complete,true);}else assert.match(first.errors[0].reason,/matching media MIME/);
  }
 }finally{evidence.publicUrl=old;}
});
test('media and HLS recovery honor the shared reservation even with local space remaining',async()=>{
 for(const status of [200,206]){
  const assets=[],errors=[];let reservations=0;
  await require('../frozen_media').complete(assets,errors,async()=>({status,headers:status===206?{'content-range':'bytes 0-3/8'}:{},body:Buffer.alloc(4)}),async()=>{},new Set(),[{url:'https://cdn.example/loaded.mp4',mime:'video/mp4'}],()=>{reservations++;throw Error('shared reservation exhausted');});
  assert.equal(reservations,1);assert.equal(assets.length,0);assert.match(errors[0].reason,/shared reservation exhausted/);
 }
 const assets=[{url:'https://cdn.example/list.m3u8',mime:'application/vnd.apple.mpegurl',body:Buffer.from('#EXTM3U\n#EXTINF:4,\nfirst.ts\n').toString('base64')}],errors=[];let reservations=0;
 await require('../declared_hls_resources').complete(assets,errors,async()=>({status:200,headers:{'content-type':'video/mp2t'},body:Buffer.alloc(4)}),async()=>{},new Set(),()=>{reservations++;throw Error('shared reservation exhausted');});
 assert.equal(reservations,1);assert.equal(assets.length,1);assert.ok(errors.some(e=>e.reason==='shared reservation exhausted'));
});

test('derived MSE byte reservation shares the native HTTP aggregate ceiling',()=>{
 const page={on(){},off(){},context:()=>({})};const collector=require('../native_resources').collect(page);
 const total=require('../evidence_limits').TOTAL_RESOURCE_BYTES;collector.reserveDerived(total-1);collector.reserveDerived(1);
 assert.throws(()=>collector.reserveDerived(1),/budget/);assert.throws(()=>collector.reserveDerived(-1),/Invalid/);
});


test('intermediate recovery captures selected images but defers unused configuration images until closure',async()=>{
 const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  let selected=[];const calls=[];const page={on(){},off(){},url:()=> 'https://example.test/',content:async()=>'<script>{"itemMediaSrc":"https://cdn.example/optional.png"}</script>',evaluate:async(fn,mode)=>mode==='image_urls'?selected:String(fn).includes('video,audio')?[]:selected,context:()=>({request:{get:async url=>{calls.push(url);return {status:()=>200,headers:()=>({'content-type':'image/png'}),body:async()=>Buffer.from('real image bytes'),dispose:async()=>{}};}}})};
  const collector=require('../native_resources').collect(page);await collector.finish({close:false});assert.deepEqual(calls,[]);
  selected=['https://cdn.example/native-selected.png'];await collector.finish({close:false});assert.deepEqual(calls,selected);
  const result=await collector.finish();assert.deepEqual(calls,['https://cdn.example/native-selected.png','https://cdn.example/optional.png']);assert.equal(result.resource_recovery_phase_version,'native-before-optional-resources-v1');
 }finally{evidence.publicUrl=old;}
});

test('image recovery shares attempt and active time limits across phases without marking unattempted URLs',async()=>{
 const state={attempted:new Set(),elapsed_ms:0},assets=[],errors=[],calls=[];
 const fetch=async url=>{calls.push(url);return {status:200,headers:{'content-type':'image/png'},body:Buffer.from('image')};};
 await complete([], 'https://example.test/',assets,errors,fetch,async()=>{},null,state);
 assert.equal(state.elapsed_ms,0);
 const all=Array.from({length:201},(_,i)=>'https://cdn.example/'+i+'.png');
 await complete(all,'https://example.test/',assets,errors,fetch,async()=>{},null,state);
 assert.equal(calls.length,200);assert.equal(state.attempted.size,200);assert.equal(state.attempted.has(all[200]),false);
 const elapsed=state.elapsed_ms;
 await complete([all[200]],'https://example.test/',assets,errors,fetch,async()=>{},null,state);
 assert.equal(calls.length,200);assert.ok(state.elapsed_ms>=elapsed);assert.ok(errors.some(e=>e.kind==='declared_image_limit'));
 const expired={attempted:new Set(),elapsed_ms:60001};
 await complete([all[200]],'https://example.test/',assets,[],fetch,async()=>{},null,expired);
 assert.equal(expired.attempted.size,0);assert.equal(calls.length,200);
});

test('native recovery prioritizes reachable images before hidden and static images within the shared cap',async()=>{
 const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  const visible='https://cdn.example/visible',hidden=Array.from({length:205},(_,i)=>'https://cdn.example/hidden'+i+'.png'),calls=[];
  const page={on(){},off(){},url:()=> 'https://example.test/',content:async()=>'<img src="https://cdn.example/static.png">',evaluate:async(fn,mode)=>mode==='image_urls'?[visible]:String(fn).includes('video,audio')?[]:hidden,context:()=>({request:{get:async url=>{
   calls.push(url);return {status:()=>200,headers:()=>({'content-type':'image/png'}),body:async()=>Buffer.from('image'),dispose:async()=>{}};
  }}})};
  const collector=require('../native_resources').collect(page);const first=await collector.finish({close:false});
  assert.deepEqual(calls,[visible]);assert.equal(first.image_recovery_priority_version,'reachable-content-current-src-v1');
  await collector.finish();assert.equal(calls.length,200);assert.equal(calls[0],visible);assert.equal(calls.includes('https://cdn.example/static.png'),false);
 }finally{evidence.publicUrl=old;}
});
