const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),{visibleEvidence}=require('../replay_admission');
test('non-scrolling documents exclude unreachable regions while retaining nested scroll reachability',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});const pixel='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2220%22 height=%2220%22/%3E';
 await page.setContent('<html><head><style>body{position:fixed;margin:0;height:5000px;overflow:hidden}img{width:20px;height:20px}</style></head><body><button>Reachable</button><img alt="Top" src="'+pixel+'"><div style="position:absolute;top:2000px"><button>Unreachable bottom</button><img alt="Bottom" src="'+pixel+'"></div><div style="height:40px;width:60px;overflow:hidden"><div style="height:500px"><button style="margin-top:200px">Nested scroll control</button><img alt="Scroll" src="'+pixel+'"></div></div><div style="height:40px;width:60px;overflow:clip"><div style="height:500px"><button style="margin-top:200px">Clipped control</button><img alt="Clipped" src="'+pixel+'"></div></div></body></html>');
 const before=await page.content(),offsets=await page.evaluate(()=>[...document.querySelectorAll('div')].map(e=>[e.scrollTop,e.scrollLeft]));const d=await visibleEvidence(page);
 assert.deepEqual(d.document_scroll_range,{x:false,y:false});assert.equal(d.visible_images,2);assert.ok(d.controls.some(c=>c.includes('Nested scroll control')));assert.ok(!d.controls.some(c=>/Unreachable|Clipped/.test(c)));assert.equal(d.visibility_version,'reachable-document-regions-v2');assert.equal(await page.content(),before);assert.deepEqual(await page.evaluate(()=>[...document.querySelectorAll('div')].map(e=>[e.scrollTop,e.scrollLeft])),offsets);
 await page.setContent('<body style="height:4000px"><button style="margin-top:2000px">Document scroll control</button></body>');const scroll=await visibleEvidence(page);assert.equal(scroll.document_scroll_range.y,true);assert.ok(scroll.controls.some(c=>c.includes('Document scroll control')));
 }finally{await browser.close();}
});

test('viewport-propagated BODY overflow preserves absolute application content without changing the document',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.setContent('<!doctype html><html><head><style>html{overflow:visible}body{margin:0;overflow:auto scroll}main{position:absolute;inset:0;height:1000px}#offscreen{position:fixed;top:2000px}#clip{height:20px;overflow:clip}#clip button{margin-top:100px}</style></head><body><main><h2>Visible application</h2><button>Search</button><div id="clip"><button>Clipped</button></div></main><button id="offscreen">Unreachable</button></body></html>');
  assert.equal(await page.locator('body').evaluate(e=>e.clientHeight),0);
  const before=await page.content(),observed=await visibleEvidence(page);
  assert.ok(observed.text.includes('Visible application'));assert.ok(observed.controls.includes('BUTTON||Search'));
  assert.ok(!observed.controls.some(c=>/Clipped|Unreachable/.test(c)));assert.equal(await page.content(),before);
  await page.setContent(before);assert.deepEqual((await visibleEvidence(page)).controls,observed.controls);
 }finally{await browser.close();}
});
test('BODY containment or non-visible HTML overflow keeps real BODY clipping active',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});
  for(const [html,body] of [['overflow:visible','contain:paint;position:relative'],['overflow:hidden','position:relative']]){
   await page.setContent('<!doctype html><html style="'+html+'"><body style="margin:0;height:0;overflow:clip;'+body+'"><main style="position:absolute;top:40px"><button>Clipped application</button></main></body></html>');
   const observed=await visibleEvidence(page);assert.equal(observed.controls.length,0);assert.equal(observed.text,'');
  }
 }finally{await browser.close();}
});

test('capture image priority uses the preservation census and leaves hidden images and tracking pixels intact',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.route('https://cdn.example/**',r=>r.abort());
  await page.setContent('<body style="position:fixed;height:5000px;overflow:hidden"><img style="display:none" src="https://cdn.example/hidden"><img width="1" height="1" alt="" src="https://cdn.example/pixel"><img width="20" height="20" alt="Visible" src="https://cdn.example/visible"><div style="height:40px;overflow:hidden"><div style="height:500px"><img style="margin-top:200px" width="20" height="20" src="https://cdn.example/reachable"></div></div><div style="position:absolute;top:2000px"><img width="20" height="20" src="https://cdn.example/unreachable"></div></body>');
  const html=await page.content(),before=await visibleEvidence(page),urls=await require('../replay_admission').visibleImageUrls(page);
  assert.deepEqual(urls,['https://cdn.example/visible','https://cdn.example/reachable']);assert.equal(before.visible_images,urls.length);
  assert.deepEqual(await visibleEvidence(page),before);assert.equal(await page.content(),html);assert.equal(await page.locator('img').count(),5);
 }finally{await browser.close();}
});
