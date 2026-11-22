const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {prepare}=require('../desktop_capture');
test('desktop preparation waits for a pending browser font request before evidence',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  let requested=false,finished=false,releaseFont;
  const pendingFont=new Promise(resolve=>{releaseFont=resolve;});
  await page.route('https://fonts.example/font.woff2',async route=>{requested=true;await pendingFont;finished=true;await route.abort();});
  await page.setContent('<style>@font-face{font-family:Delayed;src:url(https://fonts.example/font.woff2)}body{font-family:Delayed,serif}</style><p>Font loading changes text geometry</p>',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.fonts.status==='loading');
  const preparation=prepare(page);
  assert.equal(finished,false);releaseFont();await preparation;
  assert.equal(requested,true);assert.equal(finished,true);assert.equal(await page.evaluate(()=>document.fonts.status),'loaded');
 }finally{await browser.close();}
});

test('segmented capture never resizes the desktop viewport and restores scroll',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/segments-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.setContent('<style>body{margin:0;height:2300px}header{position:fixed;top:0}</style><header>Navigation</header><main>Content</main>');
  await page.evaluate(()=>scrollTo(0,120));
  const result=await require('../desktop_capture').capture(page,root+'/page.jpg');
  assert.equal(result.complete,true);assert.equal(result.segments.length,3);
  assert.ok(result.segments.every(s=>s.width===1440&&s.height===1000));
  assert.equal(await page.evaluate(()=>scrollY),120);assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});


test('capture preserves authored input styles and the complete measured document',async()=>{
 const fs=require('node:fs'),root=fs.mkdtempSync('/results/caret-');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.setContent('<input style="color: #000000 !important;" type="submit" value="Search"><textarea style="background-color: #ffffff">Content</textarea>');
  const evidence=require('../phase_evidence'),before=await evidence.observe(page,'before_capture');
  const html=await page.content();
  await require('../desktop_capture').capture(page,root+'/page.jpg');
  assert.equal(await page.content(),html);
  assert.equal((await evidence.observe(page,'after_capture')).sha256,before.sha256);
 }finally{await browser.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('native lazy image settles while its segment is visible, without changing authored loading',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('https://native-lazy.example/slow.svg',async r=>{await new Promise(resolve=>setTimeout(resolve,700));await r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="green"/></svg>'});});
  await page.route('https://native-lazy.example/',r=>r.fulfill({contentType:'text/html',body:'<body style="margin:0"><div style="height:14000px"></div><img id="lazy" loading="lazy" src="/slow.svg" width="160" height="160" alt="Green square"></body>'}));
  await page.goto('https://native-lazy.example/');
  const before=await page.content(),result=await prepare(page);
  assert.equal(await page.locator('#lazy').evaluate(e=>e.naturalWidth),160);
  assert.deepEqual(result.pending_image_segments,[]);
  assert.equal(await page.content(),before);
  assert.deepEqual(await page.evaluate(()=>[scrollX,scrollY]),[0,0]);
  assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();}
});

test('horizontal native lazy images load without rewriting source or changing acquired scroll offsets',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('https://horizontal-images.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><div id="lane" style="width:600px;overflow:auto"><div style="width:12000px"><img id="photo" loading="lazy" width="80" height="80" style="margin-left:11000px" src="/image.svg"></div></div></body></html>'}));
  await page.route('https://horizontal-images.example/image.svg',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="blue"/></svg>'}));
  await page.goto('https://horizontal-images.example/');const html=await page.content();
  assert.equal(await page.locator('#photo').evaluate(e=>e.naturalWidth),0);
  const result=await require('../desktop_capture').prepare(page);
  assert.equal(result.horizontal_image_lanes,1);assert.ok(await page.locator('#photo').evaluate(e=>e.complete&&e.naturalWidth>0));
  assert.deepEqual(await page.evaluate(()=>[scrollX,scrollY,document.querySelector('#lane').scrollLeft]),[0,0,0]);
  assert.equal(await page.content(),html);assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();}
});

test('hidden overflow carousel loads native lazy resources while clip remains untouched and scroll is restored',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('https://hidden-images.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><div id="lane" style="width:600px;overflow:hidden"><div style="width:12000px"><img id="photo" loading="lazy" width="80" height="80" style="margin-left:11000px" src="/image.svg"></div></div><div id="clip" style="width:600px;overflow:clip"><div style="width:12000px"><img id="clipped" loading="lazy" width="80" height="80" style="margin-left:11000px" src="/other.svg"></div></div></body></html>'}));
  await page.route('https://hidden-images.example/*.svg',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="blue"/></svg>'}));
  await page.goto('https://hidden-images.example/');const html=await page.content();
  assert.equal(await page.locator('#photo').evaluate(e=>e.naturalWidth),0);
  const result=await prepare(page);assert.equal(result.horizontal_image_lanes,1);
  assert.equal(await page.locator('#photo').evaluate(e=>e.naturalWidth),80);assert.equal(await page.locator('#clipped').evaluate(e=>e.naturalWidth),0);
  assert.deepEqual(await page.evaluate(()=>[scrollX,scrollY,document.querySelector('#lane').scrollLeft,document.querySelector('#clip').scrollLeft]),[0,0,0,0]);
  assert.equal(await page.content(),html);assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();}
});

test('nested vertical scroll loads deferred images when the document is only one viewport high',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('https://vertical-images.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body style="margin:0;height:100vh;overflow:hidden"><main id="lane" style="height:600px;overflow-y:auto"><div style="height:14000px"></div><img id="photo" loading="lazy" width="80" height="80" src="/image.svg"></main></body></html>'}));
  await page.route('https://vertical-images.example/image.svg',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="blue"/></svg>'}));
  await page.goto('https://vertical-images.example/');const html=await page.content();assert.equal(await page.locator('#photo').evaluate(e=>e.naturalWidth),0);
  const result=await prepare(page);assert.equal(result.prepared_segments,1);assert.equal(result.scrollable_image_containers,1);assert.equal(await page.locator('#photo').evaluate(e=>e.naturalWidth),80);
  assert.deepEqual(await page.evaluate(()=>[scrollX,scrollY,document.querySelector('#lane').scrollLeft,document.querySelector('#lane').scrollTop]),[0,0,0,0]);assert.equal(await page.content(),html);assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
 }finally{await browser.close();}
});
