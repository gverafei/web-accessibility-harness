const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const request=url=>({url:()=>url,resourceType:()=> 'script'});
test('registered modules must complete while blocked auxiliary requests do not prevent settlement',async()=>{
 const page=new EventEmitter(),module=request('https://frozen.example/module.js'),aux=request('https://unknown.example/poll');
 const tracker=require('../frozen_network').track(page,r=>r.url().startsWith('https://frozen.example/'));
 page.emit('request',module);const noise=setInterval(()=>{page.emit('request',aux);page.emit('requestfailed',aux);},10);
 setTimeout(()=>page.emit('requestfinished',module),150);
 try{const result=await tracker.settle(1000,50);assert.equal(result.status,'settled');assert.ok(result.wait_ms>=150);}
 finally{clearInterval(noise);tracker.dispose();}
});
test('an unfinished registered resource times out with its URL and type',async()=>{
 const page=new EventEmitter(),module=request('https://frozen.example/module.js');
 const tracker=require('../frozen_network').track(page,()=>true);page.emit('request',module);
 try{await assert.rejects(tracker.settle(100,20),error=>error.settlement.pending[0].url===module.url());}
 finally{tracker.dispose();}
});

test('injected browser waits for a delayed module despite recurring blocked fetches',async()=>{
 const {chromium}=require('playwright');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext(),page=await context.newPage();
  const tracker=require('../frozen_network').track(page,r=>r.url()==='https://frozen.example/module.js');
  await page.route('**/*',async route=>{
   if(route.request().url()==='https://frozen.example/module.js'){
    await new Promise(resolve=>setTimeout(resolve,350));
    return route.fulfill({contentType:'text/javascript',body:'document.querySelector("#content").textContent="Module complete"'});
   }
   if(route.request().url()==='https://frozen.example/')return route.fulfill({contentType:'text/html',body:'<body></body>'});
   return route.abort();
  });
  await page.goto('https://frozen.example/');
  await page.evaluate(()=>{document.open();document.write('<p id="content">Pending</p><script type="module" src="/module.js"></script><script>setInterval(()=>fetch("https://unknown.example/poll").catch(()=>{}),30)</script>');document.close();});
  await page.waitForFunction(()=>document.querySelector('#content'));
  const result=await tracker.settle(2000,500);
  assert.equal(result.status,'settled');assert.equal(await page.locator('#content').textContent(),'Module complete');
  tracker.dispose();
 }finally{await browser.close();}
});

test('detached frame requests cannot hold the surviving document hostage',async()=>{
 const page=new EventEmitter(),removed={},surviving={};
 const gone={...request('https://frozen.example/removed.js'),frame:()=>removed};
 const active={...request('https://frozen.example/active.js'),frame:()=>surviving};
 const tracker=require('../frozen_network').track(page,()=>true);page.emit('request',gone);page.emit('request',active);page.emit('framedetached',removed);
 try{
  await assert.rejects(tracker.settle(100,20),error=>error.settlement.pending.length===1&&error.settlement.pending[0].url===active.url());
  page.emit('requestfinished',active);assert.equal((await tracker.settle(500,20)).status,'settled');
 }finally{tracker.dispose();assert.equal(page.listenerCount('framedetached'),0);}
});

test('injected document initializes deferred scroll listeners before lazy exploration',async()=>{
 const {chromium}=require('playwright');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('**/*',async route=>{
   if(route.request().url().endsWith('/init.js')){
    await new Promise(resolve=>setTimeout(resolve,700));
    return route.fulfill({contentType:'text/javascript',body:`document.body.style.height='2400px';window.addEventListener('scroll',()=>{if(scrollY>500)document.querySelector('#deferred').textContent='Loaded';});`});
   }
   return route.fulfill({contentType:'text/html',body:'<body></body>'});
  });
  await page.goto('https://frozen.example/');
  const tracker=require('../frozen_network').track(page,()=>true);
  try {
   await require('../native_media_pause').write(page,'<body><div id="deferred">Pending</div><script defer src="/init.js"></script></body>');
   await require('../frozen_network').settleDocument(page,tracker);
   const helper=require('../run_axe');
   await helper.activateLazyContent(page,{...helper.loadPolicy({}),lazy_load_scroll:true,max_scroll_steps:6,scroll_step_px:650,scroll_delay_ms:100});
   assert.equal(await page.locator('#deferred').textContent(),'Loaded');
   assert.equal(await page.evaluate(()=>scrollY),0);
  } finally {tracker.dispose();}
 } finally {await browser.close();}
});
