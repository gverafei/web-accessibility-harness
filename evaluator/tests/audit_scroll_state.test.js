const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
test('auditor scroll restoration preserves findings input and does not erase real source mutations',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});await require('../measurement_state').install(page);
 await page.route('https://audit-scroll.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><div id="panel" style="width:150px;overflow:auto;white-space:nowrap"><span>Start</span><button style="margin-left:500px">End</button></div></body></html>'}));await page.goto('https://audit-scroll.example/');await require('../measurement_state').freeze(page);
 const phases=require('../phase_evidence'),scroll=require('../audit_scroll_state');const before=await phases.observe(page,'before');await scroll.capture(page);
 await page.evaluate(()=>document.querySelector('#panel').scrollLeft=250);assert.notEqual(before.sha256,(await phases.observe(page,'during')).sha256);
 const restored=await scroll.restore(page);assert.equal(restored.changed_containers.length,1);assert.equal(before.sha256,(await phases.observe(page,'after')).sha256);
 await scroll.capture(page);await page.evaluate(()=>{document.querySelector('#panel').scrollLeft=250;document.querySelector('span').textContent='Changed content';});await scroll.restore(page);
 assert.notEqual(before.sha256,(await phases.observe(page,'mutated')).sha256);
 }finally{await browser.close();}
});
test('restores authored smooth document and nested scrolling immediately',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.setContent('<style>html,#panel{scroll-behavior:smooth}body{height:12000px}#panel{width:100px;overflow:auto;white-space:nowrap}</style><div id="panel"><button style="margin-left:600px">End</button></div>');
  const scroll=require('../audit_scroll_state');await scroll.capture(page);
  await page.evaluate(()=>{scrollTo({top:9000,behavior:'instant'});document.querySelector('#panel').scrollTo({left:400,behavior:'instant'});});
  await scroll.restore(page);
  assert.deepEqual(await page.evaluate(()=>[scrollY,document.querySelector('#panel').scrollLeft]),[0,0]);
  await page.waitForTimeout(300);assert.deepEqual(await page.evaluate(()=>[scrollY,document.querySelector('#panel').scrollLeft]),[0,0]);
  assert.equal(await page.locator('html').evaluate(e=>getComputedStyle(e).scrollBehavior),'smooth');
 }finally{await browser.close();}
});

test('inspection-created overflow restores offsets without concealing the actual source mutation',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();await page.setContent('<div id="panel" style="width:100px;overflow:auto"><div id="content">Content</div></div>');
  const scroll=require('../audit_scroll_state'),phases=require('../phase_evidence');const before=await phases.observe(page,'before');await scroll.capture(page);
  await page.evaluate(()=>{document.querySelector('#content').style.width='500px';document.querySelector('#panel').scrollLeft=20;});
  await scroll.restore(page);assert.equal(await page.locator('#panel').evaluate(e=>e.scrollLeft),0);
  assert.notEqual(before.sha256,(await phases.observe(page,'after')).sha256);
 }finally{await browser.close();}
});
