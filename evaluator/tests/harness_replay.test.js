const test=require('node:test');const assert=require('node:assert/strict');const http=require('node:http');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {runAxeIsolated}=require('../run_axe_isolated');const {runLighthouse}=require('../run_lighthouse');
test('frozen local fixture is measured by both independent browser auditors', {timeout:90000},async()=>{
 const source='<!doctype html><html lang="en"><head><title>Offline synthetic fixture</title></head><body><main><h1>Fixture</h1><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=" alt="Fixture pixel"><section><h2>Acquired section</h2><p>Controlled content.</p><p>Additional observed content.</p></section></main></body></html>';
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end(source)});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'harness-offline-'));
 try{const url='http://127.0.0.1:'+server.address().port+'/fixture';
  const [axe,lh]=await Promise.all([runAxeIsolated(url,path.join(tmp,'page.jpg'),{standard:'wcag22aa',runtimeConfig:{page_settle_delay_ms:'0',dom_stability_window_ms:'100',dom_stability_timeout_ms:'1000',enable_lazy_load_scroll:'false'}}),runLighthouse(url)]);
  assert.equal(axe.summary.wcag_violations,0);assert.ok(lh.summary.accessibility_score>=94);assert.equal(lh.raw.configSettings.formFactor,'desktop');assert.equal(lh.raw.configSettings.screenEmulation.width,1440);assert.equal(lh.raw.configSettings.screenEmulation.height,1000);assert.ok(axe.html.includes('Controlled content.'));assert.ok(fs.statSync(path.join(tmp,'page.jpg')).size>100);
 }finally{await new Promise(resolve=>server.close(resolve));fs.rmSync(tmp,{recursive:true,force:true});}
});
