const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright'),{visibleEvidence}=require('../replay_admission');
test('frozen acquired app boots stay inert, data and native controls persist, new repair script runs',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();let calls=0;
  await page.route('https://boot.example/app.js',r=>{calls++;return r.fulfill({contentType:'text/javascript',body:"document.querySelector('main').replaceChildren()"});});
  const html=fs.readFileSync(path.join(__dirname,'fixtures/frozen_acquired_boot.html'),'utf8');
  await page.setContent(html);assert.equal(calls,0);const before=await visibleEvidence(page);assert.equal(before.controls.length,3);assert.match(before.text,/Acquired application state/);assert.equal(await page.locator('.dropdown-menu').count(),1);
  await page.setContent(html.replace('</body>','<script>document.querySelector("#repair").setAttribute("aria-label","Choose option");</script></body>'));
  assert.equal(calls,0);assert.equal(await page.locator('#repair').getAttribute('aria-label'),'Choose option');
  assert.deepEqual((await visibleEvidence(page)).controls,before.controls);assert.equal(await page.locator('script[type="application/ld+json"]').textContent(),'{"name":"Original"}');
 }finally{await browser.close();}
});
