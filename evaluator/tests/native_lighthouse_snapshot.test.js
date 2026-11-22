const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
test('native acquisition captures response, Axe and Lighthouse without a second document navigation',async()=>{
 let requests=0;
 const server=require('node:http').createServer((req,res)=>{
  if(req.url==='/')requests++;
  res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="en"><head><title>Native snapshot</title></head><body style="min-height:2500px"><header><nav><a href="#main">Skip to content</a></nav></header><main id="main"><h1>Fresh page</h1><p>This is the acquired original document.</p><button>Confirm selection</button></main><footer><p>Contact information</p></footer></body></html>');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const root=fs.mkdtempSync('/results/native-snapshot-');
 try{
  const url='http://127.0.0.1:'+server.address().port+'/';
  const result=await require('../run_axe').runAxe(url,root+'/page.jpg',{lighthouseSnapshot:true,runtimeConfig:{enable_lazy_load_scroll:false,page_settle_delay_ms:1,dom_stability_window_ms:50,dom_stability_timeout_ms:2000}});
  assert.equal(requests,1);assert.equal(result.lighthouse_result.raw.fullPageScreenshot,undefined);assert.equal(result.lighthouse_result.raw.configSettings.disableFullPageScreenshot,true);assert.equal(result.lighthouse_result.mode,'snapshot');
  assert.ok(Number.isFinite(result.lighthouse_result.summary.accessibility_score));
  assert.ok(result.response_html.includes('acquired original document'));assert.ok(fs.existsSync(result.screenshot_path));
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));fs.rmSync(root,{recursive:true,force:true});}
});
