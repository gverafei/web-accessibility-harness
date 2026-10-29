const {test}=require('node:test'),assert=require('node:assert/strict');
const {mediaTracks,contrast,collect}=require('../taxonomy_supplement');
const box=(type,data)=>{const b=Buffer.alloc(8);b.writeUInt32BE(data.length+8);b.write(type,4);return Buffer.concat([b,data]);};
const movie=types=>box('moov',Buffer.concat(types.map(t=>{const h=Buffer.alloc(12);h.write(t,8);return box('trak',box('mdia',box('hdlr',h)));})));
test('Complete frozen MP4 streams distinguish silent and audio-bearing video',()=>{
 assert.deepEqual(mediaTracks(movie(['vide'])),{complete:true,handlers:['vide'],audio_tracks:0,caption_tracks:0});
 assert.equal(mediaTracks(movie(['vide','soun'])).audio_tracks,1);
 assert.equal(mediaTracks(movie(['vide','soun','sbtl'])).caption_tracks,1);
 for(const b of [movie(['vide']).subarray(0,20),movie(['myst']),Buffer.alloc(1)])assert.equal(mediaTracks(b).complete,false);
});
test('Measured contrast uses WCAG luminance/large-text thresholds; uncertainty never passes',()=>{
 const e={color:'rgb(0, 0, 0)',fontSize:'15px',fontWeight:'400',visible:true,layers:[{backgroundColor:'rgba(0, 0, 0, 0)'},{backgroundColor:'rgb(255, 255, 255)'}]};
 assert.equal(contrast(e).ratio,21);assert.equal(contrast(e).status,'passed');
 assert.equal(contrast({...e,color:'rgb(190, 190, 190)'}).status,'failed');
 assert.equal(contrast({...e,fontWeight:'700',fontSize:'19px'}).threshold,3);
 for(const patch of [{occluded:true},{paint_complex:true},{visible:false},{color:'rgba(0, 0, 0, .5)'},{layers:[]}])assert.equal(contrast({...e,...patch}).status,'insufficient_evidence');
});
test('Supplement uses exact frozen document, desktop evidence and restores scroll',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();await page.setContent('<body style="background:white"><div style="height:1400px"></div><a id="a" style="color:black">Read more</a></body>');
 const result=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']}]}]},new Map());assert.equal(result.items[0].evidence.measurement.status,'passed');assert.equal(await page.evaluate(()=>scrollY),0);assert.equal(result.viewport.width,1440);assert.ok(result.screenshots[result.items[0].evidence.screenshot_id].body.length>100);
 }finally{await browser.close();}
});
test('Image-backed text gets painted contrast without guessing background or changing document',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();await page.setContent('<body style="background:white"><div style="background-image:linear-gradient(white,white)"><a id="a" style="color:rgb(0,136,204)">Download application</a></div></body>');
 const html=await page.content(),r=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']}]}]},new Map());const m=r.items[0].evidence.measurement;assert.equal(m.status,'failed');assert.ok(Math.abs(m.ratio-3.89351)<.00001);assert.ok(m.background_screenshot.length>0);assert.equal(await page.content(),html);assert.equal(await page.evaluate(()=>document.adoptedStyleSheets.length),0);
 }finally{await browser.close();}
});
test('Both supplementary screenshot paths preserve authored input styles and caret',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.setContent('<body style="background:white"><input id="search" style="color:#123456; caret-color: auto" value="Search"><div style="background-image:linear-gradient(white,white)"><a id="a" style="color:rgb(0,136,204)">Read more</a></div></body>');
  await page.locator('#search').focus();const html=await page.content();
  const screenshot=page.screenshot.bind(page),formats=[];
  page.screenshot=async options=>{assert.equal(options.caret,'initial');formats.push(options.type);return screenshot(options);};
  const result=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']}]}]},new Map());
  assert.equal(await page.content(),html);assert.ok(formats.includes('png')&&formats.includes('jpeg'));
  assert.equal(result.items[0].evidence.measurement.status,'failed');
  assert.equal(await page.evaluate(()=>document.adoptedStyleSheets.length),0);
 }finally{await browser.close();}
});

test('supplement inspection restores nested horizontal carousel scroll before measured phase comparison',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});await require('../measurement_state').install(page);
 await page.route('https://supplement-scroll.example/',r=>r.fulfill({contentType:'text/html',body:'<body style="background:white"><div id="carousel" style="width:150px;overflow:auto;white-space:nowrap"><a id="a" style="margin-left:500px;color:black">Read more</a></div></body>'}));await page.goto('https://supplement-scroll.example/');
 await page.evaluate(()=>document.querySelector('#carousel').scrollLeft=37);await require('../measurement_state').freeze(page);
 const phase=require('../phase_evidence'),before=await phase.observe(page,'before');
 const result=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']}]}]},new Map());
 assert.equal(result.items.length,1);assert.equal(result.items[0].evidence.measurement.status,'passed');assert.equal(result.scroll_restoration.changed_containers.length,1);
 assert.equal(await page.evaluate(()=>document.querySelector('#carousel').scrollLeft),37);assert.equal(before.sha256,(await phase.observe(page,'after')).sha256);
 }finally{await browser.close();}
});

test('painted contrast decodes evaluator pixels with source CSP intact and no external requests',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('https://csp-pixels.example/',r=>r.fulfill({contentType:'text/html',headers:{'Content-Security-Policy':"img-src 'none'; connect-src 'none'"},body:'<body style="background:white"><div style="background-image:linear-gradient(white,white)"><a id="a" style="color:rgb(0,136,204)">Download application</a></div></body>'}));
  await page.goto('https://csp-pixels.example/');const html=await page.content(),contexts=browser.contexts().length;
  const result=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']}]}]},new Map());
  const measurement=result.items[0].evidence.measurement;
  assert.equal(measurement.status,'failed');assert.ok(Math.abs(measurement.ratio-3.89351)<.00001);
  assert.equal(await page.content(),html);assert.equal(browser.contexts().length,contexts);
  assert.equal(await page.evaluate(()=>document.adoptedStyleSheets.length),0);
 }finally{await browser.close();}
});

test('same frozen viewport screenshot is reused for all target judgments without dropping criteria',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.setContent('<body style="background:white"><a id="a" style="color:black">First</a><a id="b" style="color:black">Second</a></body>');
  const result=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']},{target:['#b']}]}]},new Map());
  assert.equal(result.items.length,2);assert.equal(Object.keys(result.screenshots).length,1);
  assert.equal(result.items[0].evidence.screenshot_id,result.items[1].evidence.screenshot_id);
  assert.ok(result.items.every(x=>x.evidence.measurement.status==='passed'));
  const shot=result.screenshots[result.items[0].evidence.screenshot_id];
  assert.equal(shot.document_sha256,result.document_sha256);assert.equal(require('node:crypto').createHash('sha256').update(Buffer.from(shot.body,'base64')).digest('hex'),shot.sha256);
 }finally{await browser.close();}
});

test('painted background crops use viewport coordinates after document scrolling',async()=>{
 const {chromium}=require('playwright'),browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.setContent('<body style="background:white"><div style="height:2800px"></div><div style="background-image:linear-gradient(white,white)"><a id="a" style="color:rgb(0,136,204)">Download application</a></div></body>');
  const result=await collect(page,{incomplete:[{id:'color-contrast',nodes:[{target:['#a']}]}]},new Map()),m=result.items[0].evidence.measurement;
  assert.ok(Math.abs(m.ratio-3.89351)<.00001);assert.equal(m.status,'failed');assert.ok(m.background_screenshot_clip.y>m.background_screenshot_clip.viewport_y);assert.equal(await page.evaluate(()=>scrollY),0);
 }finally{await browser.close();}
});
