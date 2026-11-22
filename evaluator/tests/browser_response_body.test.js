const test=require('node:test'),assert=require('node:assert/strict');
const {observed}=require('../browser_response_body');
test('complete compressed wire range retains original headers and decoded entity without invented offsets',()=>{
 const body=Buffer.from('#EXTM3U\n#EXT-X-ENDLIST\n'),headers={'content-type':'application/vnd.apple.mpegurl','content-encoding':'gzip','content-range':'bytes 0-9/10','content-length':'10','access-control-allow-origin':'*'};
 const r=observed(206,headers,body);assert.equal(r.http_status,200);assert.equal(r.headers['content-range'],undefined);assert.equal(r.headers['content-encoding'],undefined);assert.equal(r.headers['access-control-allow-origin'],'*');assert.deepEqual(r.body_representation.native_headers,headers);assert.equal(r.body_representation.native_http_status,206);assert.equal(r.body_representation.logical_bytes,body.length);assert.equal(r.body_representation.wire_range_bytes,10);
 const response=require('../frozen_media').response({mime:headers['content-type'],body,...r});assert.equal(response.status,200);assert.equal(response.body,body);assert.equal(response.headers['content-length'],String(body.length));assert.equal(headers['content-range'],'bytes 0-9/10');
});
test('partial compressed, unsupported or malformed ranges cannot become full decoded resources',()=>{
 for(const h of [{'content-encoding':'gzip','content-range':'bytes 0-9/20'},{'content-encoding':'br','content-range':'bytes 10-19/20'},{'content-encoding':'gzip'},{'content-encoding':'unknown','content-range':'bytes 0-9/10'},{'content-encoding':'gzip','content-range':'bytes 0-9007199254740992/9007199254740993'}]){const r=observed(206,h,Buffer.from('decoded'));assert.equal(r.http_status,206);assert.equal(r.body_representation.kind,'unsupported_encoded_range');assert.deepEqual(r.body_representation.native_headers,h);assert.throws(()=>require('../frozen_media').response({mime:'video/webm',body:Buffer.from('decoded'),...r}),/offsets/);}
 assert.throws(()=>observed(206,{'content-encoding':'gzip','content-range':'bytes 0-9/10'},Buffer.alloc(0)),/Empty/);
 const headers={'content-range':'bytes 1-3/5'};const r=observed(206,headers,Buffer.from('abc'));assert.equal(r.http_status,206);assert.equal(r.headers['content-range'],headers['content-range']);
 const full=observed(200,{'content-encoding':'br','content-length':'3'},Buffer.from('already decoded'));assert.equal(full.http_status,200);assert.equal(full.headers['content-encoding'],undefined);assert.equal(full.body_representation.native_headers['content-encoding'],'br');
});
test('real browser decoded complete gzip range is frozen once and replays through the actual decoder',async()=>{
 const http=require('node:http'),zlib=require('node:zlib'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{chromium}=require('playwright'),evidence=require('../harness_evidence'),old=evidence.publicUrl;
 const bytes=Buffer.alloc(48044);bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVEfmt ',8);bytes.writeUInt32LE(16,16);bytes.writeUInt16LE(1,20);bytes.writeUInt16LE(1,22);bytes.writeUInt32LE(8000,24);bytes.writeUInt32LE(16000,28);bytes.writeUInt16LE(2,32);bytes.writeUInt16LE(16,34);bytes.write('data',36);bytes.writeUInt32LE(bytes.length-44,40);
 const wire=zlib.gzipSync(bytes),server=http.createServer((req,res)=>{if(req.url==='/sound'){res.writeHead(206,{'content-type':'audio/wav','content-encoding':'gzip','content-range':`bytes 0-${wire.length-1}/${wire.length}`,'content-length':wire.length});res.end(wire);}else{res.writeHead(200,{'content-type':'text/html'});res.end('<html><body>Native response fixture</body></html>');}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;const root=fs.mkdtempSync('/results/decoded-wire-');
 try{
  const origin='http://127.0.0.1:'+server.address().port+'/',url=origin+'sound';browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});const page=await browser.newPage(),collector=require('../native_resources').collect(page);await collector.ready;await page.goto(origin);await page.evaluate(u=>fetch(u).then(r=>r.arrayBuffer()),url);
  const packet=await collector.finish(),asset=packet.assets.find(a=>a.url===url);assert.equal(asset.http_status,200);assert.equal(asset.body_representation.native_http_status,206);assert.equal(asset.body_representation.native_headers['content-encoding'],'gzip');assert.deepEqual(Buffer.from(asset.body,'base64'),bytes);assert.equal(asset.body_representation.wire_range_bytes,wire.length);
  await browser.close();browser=null;await new Promise(r=>server.close(r));evidence.publicUrl=async()=>{};
  const file=path.join(root,'manifest.json');fs.writeFileSync(file,JSON.stringify({version:'original-origin-injection-v2',origin,document:'<html><body><audio controls preload="none" src="'+url+'"></audio></body></html>',assets:[asset],media_reference:[{position_version:'observed-media-position-v1',position_path:'html > body:nth-of-type(1) > audio:nth-of-type(1)',state:'loaded',ready_state:4,paused:true,current_time:0.5,current_src:url,media_source:null,identity:{kind:'AUDIO',preload:'none',poster:'',sources:[url]}}]}));
  const result=await require('../origin_snapshot').run(file,path.join(root,'replay'),true);assert.equal(result.media_restoration.results[0].status,'restored');assert.equal(result.media_restoration.results[0].time,0.5);assert.equal(result.broken_media,0);assert.equal(result.live_network,false);
 }finally{evidence.publicUrl=old;if(browser)await browser.close();if(server.listening)await new Promise(r=>server.close(r));fs.rmSync(root,{recursive:true,force:true});}
});


test('native response ordinals are captured before asynchronous body completion',async()=>{
 const listeners=new Map();let finishFirst;
 const page={context:()=>({}),on:(name,fn)=>listeners.set(name,fn),off:()=>{},content:async()=>'<html></html>',url:()=> 'https://example.org/'};
 const collector=require('../native_resources').collect(page);await collector.ready;
 const response=(id,body)=>({url:()=>`https://example.org/${id}`,status:()=>200,headers:()=>({'content-type':'text/plain'}),request:()=>({method:()=> 'GET',redirectedFrom:()=>null}),body:()=>body});
 listeners.get('response')(response('first',new Promise(resolve=>finishFirst=resolve)));
 listeners.get('response')(response('second',Promise.resolve(Buffer.from('second'))));
 await new Promise(resolve=>setImmediate(resolve));finishFirst(Buffer.from('first'));
 const result=await collector.finish();assert.equal(result.native_response_order_version,'browser-response-sequence-v1');
 assert.deepEqual(result.assets.map(a=>[a.url.split('/').at(-1),a.native_response_sequence]),[['second',2],['first',1]]);
});

test('non-retained methods, redirects and errors do not starve the native body budget',async()=>{
 const listeners=new Map(),page={context:()=>({}),on:(name,fn)=>listeners.set(name,fn),off(){},content:async()=>'<html></html>',url:()=> 'https://example.org/'};
 const collector=require('../native_resources').collect(page);await collector.ready;let reads=0;
 const response=(method,status,id)=>({url:()=>`https://example.org/${id}`,status:()=>status,headers:()=>({'content-type':'text/plain'}),request:()=>({method:()=>method,redirectedFrom:()=>null}),body:async()=>{reads++;return Buffer.from('actual');}});
 for(let i=0;i<1000;i++){listeners.get('response')(response('POST',200,'post'));listeners.get('response')(response('OPTIONS',204,'cors'));listeners.get('response')(response('GET',302,'redirect'));listeners.get('response')(response('GET',404,'error'));}
 listeners.get('response')(response('GET',200,'needed-image'));const result=await collector.finish();assert.equal(reads,1);assert.equal(result.assets.length,1);assert.equal(result.assets[0].native_response_sequence,4001);assert.equal(result.native_response_capture_scope_version,'successful-get-body-budget-v1');assert.deepEqual(result.errors,[]);
});
test('eligible native body attempts remain capped at1000 including failed reads',async()=>{
 const listeners=new Map(),page={context:()=>({}),on:(name,fn)=>listeners.set(name,fn),off(){},content:async()=>'<html></html>',url:()=> 'https://example.org/'};
 const collector=require('../native_resources').collect(page);await collector.ready;let reads=0;
 for(let i=0;i<1001;i++)listeners.get('response')({url:()=>`https://example.org/${i}`,status:()=>200,headers:()=>({'content-type':'text/plain'}),request:()=>({method:()=> 'GET',redirectedFrom:()=>null}),body:async()=>{reads++;throw Error('Native body unavailable');}});
 const result=await collector.finish();assert.equal(reads,1000);assert.equal(result.assets.length,0);assert.equal(result.errors.filter(e=>e.reason==='resource response count limit').length,1);assert.equal(result.errors.filter(e=>e.reason==='Native body unavailable').length,1000);
});
