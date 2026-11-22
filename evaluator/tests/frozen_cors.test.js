const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const cors=require('../frozen_cors');
function recorded(extra={}){return {version:cors.VERSION,url:'https://api.example.com/data',status:204,request_headers:{origin:'https://example.com','access-control-request-method':'GET','access-control-request-headers':'x-client'},headers:{'access-control-allow-origin':'https://example.com','access-control-allow-methods':'GET','access-control-allow-headers':'x-client'},...extra};}
test('frozen preflight matches exact URL, origin, GET and requested header set',()=>{
 const entry=recorded(),map=cors.index([entry],'https://example.com/');
 assert.deepEqual(map.lookup(entry.url,entry.request_headers),{status:204,headers:entry.headers});
 for(const changed of [{origin:'https://other.example'},{'access-control-request-method':'POST'},{'access-control-request-headers':'x-other'}])assert.equal(map.lookup(entry.url,{...entry.request_headers,...changed}),undefined);
 assert.equal(map.lookup(entry.url+'?different=1',entry.request_headers),undefined);
 assert.throws(()=>cors.index([recorded({request_headers:{...entry.request_headers,'access-control-request-method':'POST'}})],'https://example.com/'),/Invalid/);
 assert.throws(()=>cors.index([recorded({headers:{'access-control-allow-origin':'*\r\nextra: yes'}})],'https://example.com/'),/Invalid/);
 const conflict=cors.index([entry,recorded({headers:{...entry.headers,'access-control-allow-origin':'*'}}),entry],'https://example.com/');
 assert.equal(conflict.lookup(entry.url,entry.request_headers),undefined);assert.equal(conflict.ambiguous.length,1);
});
function listen(server){return new Promise(resolve=>server.listen(0,'127.0.0.1',()=>resolve('http://127.0.0.1:'+server.address().port)));}
function close(server){return new Promise(resolve=>server.close(resolve));}
test('native CDP records actual GET preflight and replay reads frozen JSON with both servers stopped',async()=>{
 const {chromium}=require('playwright');let origin,api,document,requests=[];
 const main=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end(document);});
 const data=http.createServer((req,res)=>{requests.push(req.method);res.setHeader('Access-Control-Allow-Origin',origin);if(req.method==='OPTIONS'){res.setHeader('Access-Control-Allow-Methods','GET');res.setHeader('Access-Control-Allow-Headers','x-client');res.setHeader('Vary',['Access-Control-Request-Method','Access-Control-Request-Headers']);res.writeHead(204);res.end();}else{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({text:'Frozen API content'}));}});
 const root=fs.mkdtempSync('/results/read-cors-'),evidence=require('../harness_evidence'),old=evidence.publicUrl;
 let browser;
 try{
  origin=await listen(main);api=await listen(data);
  document='<!doctype html><html lang="en"><head><title>Read API</title></head><body><main><h1 id="result">Loading</h1></main><script>fetch('+JSON.stringify(api+'/data')+',{headers:{"x-client":"fixture"}}).then(r=>r.json()).then(d=>document.getElementById("result").textContent=d.text)</script></body></html>';
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage(require('../desktop_profile').contextOptions()),collector=require('../native_resources').collect(page);await collector.ready;
  await page.goto(origin);await page.waitForFunction(()=>document.getElementById('result').textContent==='Frozen API content');
  const capture=await collector.finish();assert.equal(capture.preflights.length,1);assert.equal(capture.preflights[0].status,204);assert.equal(capture.preflights[0].headers['access-control-allow-headers'],'x-client');assert.deepEqual(requests,['OPTIONS','GET']);
  await browser.close();browser=null;await close(main);await close(data);
  const input=path.join(root,'manifest.json');fs.writeFileSync(input,JSON.stringify({version:require('../origin_snapshot').VERSION,origin:origin+'/',document,assets:capture.assets.filter(a=>a.url!==origin+'/'),preflights:capture.preflights,runtime_config:{enable_lazy_load_scroll:false,page_settle_delay_ms:1,dom_stability_window_ms:50,dom_stability_timeout_ms:2000}}));
  evidence.publicUrl=async u=>u;
  const result=await require('../origin_snapshot').run(input,path.join(root,'out'),true);
  assert.match(result.text,/Frozen API content/);assert.equal(result.live_network,false);assert.equal(result.blocked_operations.filter(r=>r.method==='OPTIONS').length,0);assert.deepEqual(requests,['OPTIONS','GET']);
 }finally{if(browser)await browser.close();if(main.listening)await close(main);if(data.listening)await close(data);evidence.publicUrl=old;fs.rmSync(root,{recursive:true,force:true});}
});

test('CDP repeated Vary fields preserve their tokens without permitting header injection',()=>{
 const entry=recorded({headers:{'access-control-allow-origin':'https://example.com',vary:'Access-Control-Request-Method\nAccess-Control-Request-Headers'}});
 const map=cors.index([entry],'https://example.com/');
 assert.equal(map.lookup(entry.url,entry.request_headers).headers.vary,'Access-Control-Request-Method, Access-Control-Request-Headers');
 assert.equal(entry.headers.vary,'Access-Control-Request-Method\nAccess-Control-Request-Headers');
 for(const value of ['Origin\r\nInjected: yes','Origin\nInjected: yes','Origin\n','Origin\n bad value'])
  assert.throws(()=>cors.index([recorded({headers:{vary:value}})],'https://example.com/'),/Invalid/);
 assert.throws(()=>cors.index([recorded({headers:{'access-control-allow-origin':'https://example.com\n*'}})],'https://example.com/'),/Invalid/);
});
