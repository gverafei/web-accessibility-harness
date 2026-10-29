const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {VERSION,readManifest,run}=require('../origin_snapshot');
function manifest(root,extra={}){const body=Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="green"/></svg>');const value={version:VERSION,origin:'https://example.com/',document:'<!doctype html><html lang="en"><head><title>Test</title></head><body><main><h1>Snapshot</h1><img alt="Test" src="/image,a.svg"><img alt="Missing" src="/missing.svg"><button>Action</button></main></body></html>',assets:[{url:'https://example.com/image,a.svg',mime:'image/svg+xml',body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex')}],runtime_config:{enable_lazy_load_scroll:false,page_settle_delay_ms:1,dom_stability_window_ms:50,dom_stability_timeout_ms:2000},...extra};const filename=path.join(root,'manifest.json');fs.writeFileSync(filename,JSON.stringify(value));return filename;}
test('browser replay fetches recorded media tail at original offsets instead of shifting it to zero',async()=>{
 const root=fs.mkdtempSync('/results/origin-partial-media-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{
  const assets=[[0,'0123'],[8,'89']].map(([start,text])=>{const body=Buffer.from(text);return {url:'https://example.com/movie.webm',mime:'video/webm',http_status:206,headers:{'content-range':`bytes ${start}-${start+body.length-1}/10`},body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex')};});
  const document='<!doctype html><html><body><h1 id="result">Loading</h1><script>fetch("/movie.webm",{headers:{Range:"bytes=8-9"}}).then(async r=>{document.getElementById("result").textContent=r.status+" "+r.headers.get("content-range")+" "+await r.text()})</script></body></html>';
  const input=manifest(root,{assets,document});const frozen=readManifest(input,root);assert.equal(frozen.assets.size,1);assert.equal(frozen.assets.values().next().value.total,10);
  const result=await run(input,path.join(root,'out'),true);assert.match(result.text,/206 bytes 8-9\/10 89/);assert.equal(result.live_network,false);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});
test('denied scripted navigation preserves the frozen document and original origin',async()=>{
 const root=fs.mkdtempSync('/results/origin-navigation-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{
  const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Navigation</title></head><body><main><h1>Frozen source</h1><button>Action</button></main><script>location.href="https://elsewhere.test/"</script></body></html>'});
  const result=await run(input,path.join(root,'out'));
  assert.equal(result.status,'completed');assert.equal(result.transport.realm.origin,'https://example.com');assert.equal(result.transport.phase_evidence.stable,true);
  assert.ok(result.transport.blocked_operations.some(r=>r.kind==='document_navigation'&&r.url==='https://elsewhere.test/'));
  assert.ok(fs.readFileSync(result.source_snapshot_path,'utf8').includes('Frozen source'));
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});
test('manifest boundaries and checksums reject unsafe or changed input',()=>{const root=fs.mkdtempSync(path.join(os.tmpdir(),'origin-'));try{const file=manifest(root);assert.equal(readManifest(file,root).assets.size,1);assert.throws(()=>readManifest(file,path.join(root,'other')));const value=JSON.parse(fs.readFileSync(file));value.assets[0].sha256='0'.repeat(64);fs.writeFileSync(file,JSON.stringify(value));assert.throws(()=>readManifest(file,root),/checksum/);}finally{fs.rmSync(root,{recursive:true,force:true});}});
test('same origin injected document supplies screenshot Axe and Lighthouse snapshot',async()=>{const root=fs.mkdtempSync('/results/origin-test-');const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;try{const input=manifest(root);const frozen=JSON.parse(fs.readFileSync(input));frozen.document=frozen.document.replace('/image,a.svg','/old-image,a.svg');frozen.assets[0].redirect_chain=[{from:'https://example.com/old-image,a.svg',to:frozen.assets[0].url,status:302,headers:{}}];fs.writeFileSync(input,JSON.stringify(frozen));const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed',JSON.stringify(result.transport.phase_evidence));assert.equal(result.transport.phase_evidence.stable,true);assert.equal(result.transport.phase_evidence.phases.length,4);assert.equal(result.transport.realm.origin,'https://example.com');assert.equal(result.transport.realm.secure,true);assert.equal(result.transport.visible.broken_images,1,JSON.stringify({failed:result.transport.request_failures,missing:result.transport.missing_resources,errors:result.transport.console_errors}));assert.ok(result.transport.missing_resources.includes('https://example.com/missing.svg'));assert.equal(result.transport.live_network,false);assert.ok(Number.isFinite(result.axe.wcag_violations));assert.ok(Number.isFinite(result.lighthouse.accessibility_score));const lhr=JSON.parse(fs.readFileSync(result.lighthouse.raw_path));assert.equal(lhr.gatherMode,'snapshot');assert.equal(lhr.configSettings.formFactor,'desktop');assert.equal(lhr.configSettings.screenEmulation.disabled,true);assert.deepEqual(result.transport.phase_evidence.phases.map(p=>p.viewport),Array(4).fill([1440,1000]));assert.ok(fs.statSync(result.screenshot_path).size>0);}finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}});

test('large captured imagery is admitted while script and aggregate limits stay bounded',()=>{const root=fs.mkdtempSync(path.join(os.tmpdir(),'origin-image-'));try{const body=Buffer.alloc(6600000);const asset={url:'https://example.com/large.gif',mime:'image/gif',body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex')};const file=manifest(root,{assets:[asset]});assert.equal(readManifest(file,root).assets.values().next().value.body.length,6600000);asset.mime='text/javascript';manifest(root,{assets:[asset]});assert.equal(readManifest(file,root).assets.values().next().value.body.length,6600000);const bundle=Buffer.alloc(10875539);asset.body=bundle.toString('base64');asset.sha256=crypto.createHash('sha256').update(bundle).digest('hex');assert.equal(readManifest(manifest(root,{assets:[asset]}),root).assets.values().next().value.body.length,10875539);asset.mime='application/octet-stream';manifest(root,{assets:[asset]});assert.throws(()=>readManifest(file,root),/size/);const large=Buffer.alloc(16000001);asset.mime='text/javascript';asset.body=large.toString('base64');asset.sha256=crypto.createHash('sha256').update(large).digest('hex');manifest(root,{assets:[asset]});assert.throws(()=>readManifest(file,root),/size/);}finally{fs.rmSync(root,{recursive:true,force:true});}});

test('scheduled dynamic content is frozen before same-document measurement',async()=>{
 const root=fs.mkdtempSync('/results/origin-changing-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Changing fixture</title></head><body><main><h1 id="counter">0</h1></main><script>setInterval(()=>{document.getElementById("counter").textContent+="x"},30)</script></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);assert.ok(result.transport.measurement_state.intervals>0);assert.ok(fs.existsSync(result.screenshot_path));assert.ok(fs.existsSync(result.axe.raw_path));assert.equal(result.transport.live_network,false);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

 test('full-page screenshot restores desktop layout with a custom scrollbar',async()=>{
 const root=fs.mkdtempSync('/results/origin-scrollbar-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Scrollbar</title><style>::-webkit-scrollbar{width:3px}body{margin:0}main{height:2400px;width:100%}</style></head><body><main><h1>Desktop</h1></main></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
 });

test('screenshot caret cleanup does not invalidate an unchanged input',async()=>{
 const root=fs.mkdtempSync('/results/origin-caret-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Input</title></head><body><main><h1>Search</h1><label for="query">Search</label><input id="query" placeholder="Search"></main></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);assert.equal(result.transport.phase_evidence.dom_normalization,'inert-document-empty-style-head-script-hints-v3');
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('capture never creates an inline style that activates outline selectors',async()=>{
 const root=fs.mkdtempSync('/results/origin-style-selector-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Input style</title><style>input[style]{outline:10px solid red}</style></head><body><main><h1>Search</h1><label for="query">Search</label><input id="query"></main></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('capture never creates an inline style that displaces a control',async()=>{
 const root=fs.mkdtempSync('/results/origin-margin-selector-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Input margin</title><style>input[style]{margin-left:20px}</style></head><body><main><h1>Search</h1><label for="query">Search</label><input id="query"></main></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

 test('measurement scrolling cannot change a source navigation state',async()=>{
 const root=fs.mkdtempSync('/results/origin-scroll-state-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Scrolling</title></head><body><header id="nav">Menu</header><main style="height:2400px"><h1>Content</h1></main><script>addEventListener("scroll",()=>document.getElementById("nav").className=scrollY ? "hidden" : "changed")</script></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);assert.equal(result.transport.measurement_state.scroll_callbacks_suspended,true);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
 });

test('scroll-revealed CSS pulse animations remain frozen through audits',async()=>{
 const root=fs.mkdtempSync('/results/origin-animation-test-');const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{
  const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Pulse</title><style>@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}.region{content-visibility:auto;contain-intrinsic-size:100px;margin-top:1500px}.pulse{height:28px;background:blue;animation:pulse .15s infinite}</style></head><body><main><h1>Stable page</h1><section class="region"><h2>Later content</h2><div class="pulse">Visible status</div></section></main></body></html>'});
  const result=await run(input,path.join(root,'out'));
  assert.equal(result.status,'completed',JSON.stringify(result.transport.phase_evidence.differences.map(d=>({phase:d.phase,entries:(d.entries||[]).map(e=>({before:e.before?.slice(0,18),after:e.after?.slice(0,18)}))}))));
  assert.equal(result.transport.phase_evidence.stable,true);
  assert.equal(result.transport.measurement_state.future_animations_suspended,true);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('measurement scrolling suspends acquired resize and mutation observers',async()=>{
 const root=fs.mkdtempSync('/results/origin-observer-test-');const evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{
  const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Observers</title></head><body><main style="height:2400px"><h1>Content</h1></main><script>new ResizeObserver(()=>{}).observe(document.body);new MutationObserver(()=>{}).observe(document.body,{childList:true,subtree:true});</script></body></html>'});
  const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');
  assert.ok(result.transport.measurement_state.resize_observers>=1);assert.ok(result.transport.measurement_state.mutation_observers>=1);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('acquired documents above two megabytes replay without truncation, with a UTF8 byte ceiling',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'origin-document-'));
 try{const document='<html><body>'+ 'x'.repeat(4100000)+'</body></html>';
 const file=manifest(root,{document});assert.equal(readManifest(file,root).document,document);
 manifest(root,{document:'é'.repeat(4000001)});assert.throws(()=>readManifest(file,root),/Invalid origin snapshot/);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('ambiguous auxiliary redirects are blocked and recorded without rejecting the whole document',async()=>{
 const root=fs.mkdtempSync('/results/origin-ambiguous-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const assets=['a','b'].map(id=>{const body=Buffer.from('void 0');const url='https://example.com/'+id+'.js';return {url,mime:'application/javascript',body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex'),redirect_chain:[{from:'https://example.com/tracker.js',to:url,status:302,headers:{}}]};});
 const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Content</title></head><body><main><h1>Retained content</h1><button>Action</button></main><script src="/tracker.js"></script></body></html>',assets});
 const result=await run(input,path.join(root,'out'));
 assert.equal(result.status,'completed');assert.equal(result.screenshot_mode,'desktop_viewport_segments');
 assert.equal(result.transport.ambiguous_redirects.length,1);assert.equal(result.transport.ambiguous_redirects[0].variants.length,2);
 assert.ok(result.transport.blocked_ambiguous_redirects.includes('https://example.com/tracker.js'));assert.equal(result.transport.live_network,false);
 assert.ok(result.transport.request_failures.length>0);assert.ok(result.transport.visible.text.includes('Retained content'));
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('measurement capture suspends hover callbacks after desktop settling',async()=>{
 const root=fs.mkdtempSync('/results/origin-hover-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Hover</title></head><body><main style="height:2400px"><h1>Desktop</h1><script>addEventListener("scroll",()=>document.querySelector("h1").classList.toggle("hover"));addEventListener("mouseover",()=>document.querySelector("h1").classList.add("shimmer-hover"));</script></main></body></html>'});
 const result=await run(input,path.join(root,'out'));assert.equal(result.status,'completed');assert.equal(result.transport.phase_evidence.stable,true);assert.equal(result.transport.measurement_state.hover_callbacks_suspended,true);assert.deepEqual(result.transport.phase_evidence.phases.map(p=>p.viewport),Array(4).fill([1440,1000]));
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('injected UTF8 document preserves external script strings without a script charset header',async()=>{
 const root=fs.mkdtempSync('/results/origin-utf8-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const body=Buffer.from('document.querySelector("h1").textContent="搜索 新闻 日本語";');
 const input=manifest(root,{document:'<!doctype html><html lang="zh"><head><title>Unicode</title></head><body><main><h1>Initial</h1><script src="/app.js"></script></main></body></html>',assets:[{url:'https://example.com/app.js',mime:'text/javascript',body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex')}]});
 const result=await run(input,path.join(root,'out'),true);assert.ok(result.text.includes('搜索 新闻 日本語'),result.text);assert.equal(result.realm.character_set,'UTF-8');assert.equal(result.broken_images,0);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('replay admission observes lazy content after the same segment preparation as captured acquisition',async()=>{
 const root=fs.mkdtempSync('/results/origin-segment-visible-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{const input=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Segment evidence</title><style>html{scroll-behavior:smooth}</style></head><body><main><h1>Initial page</h1><div id="grow" style="height:4500px"></div><p id="probe">Not loaded</p></main><script>new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){const grow=document.querySelector("#grow");if(grow.style.height==="4500px")grow.style.height="35000px";else document.querySelector("#probe").textContent="Loaded complete segment context";}}).observe(document.querySelector("#probe"));</script></body></html>',assets:[]});
 const result=await run(input,path.join(root,'out'),true);assert.ok(result.text.includes('Loaded complete segment context'),result.text);assert.equal(result.visible_evidence_policy,'stabilized-document-after-segment-preparation-v1');assert.deepEqual(result.viewport,{width:1440,height:1000});
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('frozen child frame resources settle through a single authoritative routing layer',async()=>{
 const root=fs.mkdtempSync('/results/origin-child-routing-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async u=>u;
 try{
  const asset=(url,mime,html)=>{const body=Buffer.from(html);return {url,mime,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex')};};
  const file=manifest(root,{document:'<!doctype html><html lang="en"><head><title>Child resources</title></head><body><main><h1>Frozen page</h1><iframe title="Supporting panel" src="https://example.com/panel"></iframe></main></body></html>',assets:[asset('https://example.com/panel','text/html','<html><body><img alt="Marker" src="/marker.svg"><script src="/panel.js"></script></body></html>'),asset('https://example.com/marker.svg','image/svg+xml','<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="green"/></svg>'),asset('https://example.com/panel.js','text/javascript','document.body.dataset.ready="true";')]});
  const result=await run(file,path.join(root,'out'),true);
  assert.equal(result.resource_settlement.status,'settled');assert.equal(result.live_network,false);
  assert.equal(result.request_failures.length,0,JSON.stringify(result.request_failures));
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('loaded direct media restores through an original redirect retained after identical-body deduplication',async()=>{
 const root=fs.mkdtempSync('/results/media-alias-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;evidence.publicUrl=async()=>{};
 try{
  const bytes=Buffer.alloc(48044);bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVEfmt ',8);bytes.writeUInt32LE(16,16);bytes.writeUInt16LE(1,20);bytes.writeUInt16LE(1,22);bytes.writeUInt32LE(8000,24);bytes.writeUInt32LE(16000,28);bytes.writeUInt16LE(2,32);bytes.writeUInt16LE(16,34);bytes.write('data',36);bytes.writeUInt32LE(bytes.length-44,40);
  const original='https://example.com/alias.wav',final='https://cdn.example.com/sound.wav';
  const reference={position_version:'observed-media-position-v1',position_path:'html > body:nth-of-type(1) > audio:nth-of-type(1)',state:'loaded',ready_state:4,paused:true,current_time:0.5,current_src:original,media_source:null,identity:{kind:'AUDIO',preload:'none',poster:'',sources:[original]}};
  const file=manifest(root,{document:'<html><body><audio controls preload="none" src="'+original+'"></audio></body></html>',assets:[{url:final,mime:'audio/wav',body:bytes.toString('base64'),sha256:crypto.createHash('sha256').update(bytes).digest('hex'),redirect_chain:[],additional_redirect_chains:[[{from:original,to:final,status:302,headers:{}}]]}],media_reference:[reference]});
  const result=await run(file,path.join(root,'replay'),true);assert.equal(result.media_restoration.eligible,1);assert.equal(result.media_restoration.results[0].status,'restored');assert.equal(result.broken_media,0);assert.equal(result.media_descriptors[0].current_time,0.5);assert.equal(result.live_network,false);
 }finally{evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('fragment media keys merge verified full and partial bodies without rewriting original manifest',()=>{
 const root=fs.mkdtempSync('/results/origin-fragment-media-');try{
  const url='https://example.com/video.webm',full=Buffer.from('0123456789');
  const asset=(url,body,status,headers={})=>({url,mime:'video/webm',http_status:status,headers,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex')});
  const assets=[asset(url,full.subarray(5),206,{'content-range':'bytes 5-9/10'}),asset(url+'#t=0.1',full,200)];
  const file=manifest(root,{assets}),original=fs.readFileSync(file,'utf8'),frozen=readManifest(file,root);
  assert.equal(frozen.assets.size,1);assert.ok(frozen.assets.get(url).body.equals(full));assert.equal(fs.readFileSync(file,'utf8'),original);
  const corrupt=[asset(url,Buffer.from('wrong'),206,{'content-range':'bytes 5-9/10'}),assets[1]];assert.throws(()=>readManifest(manifest(root,{assets:corrupt}),root),/Conflicting frozen media bytes/);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('snapshot transport includes more than 1000 native and recovered entries without dropping bytes',()=>{
 const root=fs.mkdtempSync('/results/origin-entry-cap-');
 try{
  const body=Buffer.from('observed resource'),sha256=crypto.createHash('sha256').update(body).digest('hex');
  const assets=Array.from({length:1035},(_,i)=>({url:'https://example.com/resource/'+i,mime:'text/plain',body:body.toString('base64'),sha256,http_status:200}));
  const frozen=readManifest(manifest(root,{assets}),root);assert.equal(frozen.assets.size,1035);assert.deepEqual(frozen.assets.get(assets[1034].url).body,body);
  const cap=require('../evidence_limits').SNAPSHOT_ASSET_ENTRIES;
  const many=Array.from({length:cap+1},(_,i)=>({...assets[0],url:'https://example.com/resource/'+i}));
  assert.throws(()=>readManifest(manifest(root,{assets:many}),root),/Invalid origin snapshot manifest/);
  assets[1034]={...assets[1034],sha256:'0'.repeat(64)};
  assert.throws(()=>readManifest(manifest(root,{assets}),root),/checksum/);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
