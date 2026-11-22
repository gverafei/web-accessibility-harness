const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
test('measurement viewport notifications cannot reinitialize an acquired carousel',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await require('../measurement_state').install(page);
  await page.route('https://resize.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><ul id="gallery" style="transform:translate3d(0px,0px,0px)"><li>Slide</li></ul><script>addEventListener("resize",()=>document.querySelector("#gallery").style.transition="none")</script></body></html>'}));
  await page.goto('https://resize.example/');
  const frozen=await require('../measurement_state').freeze(page),before=await page.content();
  await page.evaluate(()=>dispatchEvent(new Event('resize')));
  assert.equal(await page.content(),before);assert.equal(frozen.resize_callbacks_suspended,true);
  await page.evaluate(()=>{
   new ResizeObserver(()=>document.body.dataset.lateResize='changed').observe(document.body);
   new MutationObserver(()=>document.body.dataset.lateMutation='changed').observe(document.body,{childList:true});
   document.body.append(document.createComment('observer test'));
  });
  await page.waitForTimeout(150);
  assert.equal(await page.getAttribute('body','data-late-resize'),null);
  assert.equal(await page.getAttribute('body','data-late-mutation'),null);
 }finally{await browser.close();}
});

test('inactive scroll timelines do not hang measurement or fabricate a settled pause',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});await require('../measurement_state').install(page);
  await page.route('https://scroll-timeline.example/',r=>r.fulfill({contentType:'text/html',body:'<html><head><style>@keyframes reveal{from{opacity:0}to{opacity:1}}p{animation:reveal 1s linear;animation-timeline:scroll(root block)}</style></head><body><p>Inactive scrolling animation</p></body></html>'}));
  await page.goto('https://scroll-timeline.example/');
  assert.equal(await page.evaluate(()=>document.getAnimations()[0].timeline.constructor.name),'ScrollTimeline');
  let timer;
  const result=await Promise.race([require('../measurement_state').freeze(page),new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('Unbounded animation wait')),5000))]);clearTimeout(timer);
  assert.equal(result.animation_pause_settled,false);assert.equal(result.pending_animation_pauses,1);assert.equal(result.animation_pause_wait_ms,1000);
 }finally{await browser.close();}
});

test('worker and live WebSocket feeds preserve the acquired state without closing connections',async()=>{
 const http=require('node:http'),{Server:WebSocketServer}=require('ws');let tick=0,closed=0;
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<html><body><span id="feed">0</span><span id="worker">0</span><script>const w=new Worker(URL.createObjectURL(new Blob(["setInterval(()=>postMessage(Date.now()),20)"],{type:"text/javascript"})));w.onmessage=e=>document.querySelector("#worker").textContent=e.data;const socket=new WebSocket("ws://"+location.host);socket.onmessage=e=>document.querySelector("#feed").textContent=e.data</script></body></html>');});
 const sockets=new WebSocketServer({server});sockets.on('connection',socket=>socket.on('close',()=>closed++));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const timer=setInterval(()=>{tick++;for(const socket of sockets.clients)if(socket.readyState===1)socket.send(String(tick));},20);
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const context=await browser.newContext();const page=await context.newPage();await require('../measurement_state').install(page);await page.goto('http://127.0.0.1:'+server.address().port+'/');
 await page.waitForFunction(()=>document.querySelector('#feed').textContent!=='0'&&document.querySelector('#worker').textContent!=='0');
 const frozen=await require('../measurement_state').freeze(page);const before=await page.content();await page.waitForTimeout(150);
 assert.equal(await page.content(),before);assert.equal(frozen.live_transports,2);assert.equal(frozen.live_transport_callbacks_suspended,true);assert.equal(closed,0);
 const audit=await new(require('@axe-core/playwright').default)({page}).analyze();assert.ok(Array.isArray(audit.violations));
 }finally{clearInterval(timer);await browser.close();for(const socket of sockets.clients)socket.terminate();await new Promise(resolve=>sockets.close(resolve));await new Promise(resolve=>server.close(resolve));}
});

test('measurement focus remains real without moving an overflow carousel',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();await require('../measurement_state').install(page);
 await page.route('https://focus-scroll.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><div id="panel" style="width:150px;overflow:auto;white-space:nowrap"><button>Start</button><button id="last" style="margin-left:500px">End</button></div></body></html>'}));
 await page.goto('https://focus-scroll.example/');await page.evaluate(()=>document.querySelector('#last').focus());assert.ok(await page.evaluate(()=>document.querySelector('#panel').scrollLeft)>0);
 await page.evaluate(()=>{document.querySelector('#last').blur();document.querySelector('#panel').scrollLeft=0;});
 const result=await require('../measurement_state').freeze(page);await page.evaluate(()=>document.querySelector('#last').focus());
 assert.deepEqual(await page.evaluate(()=>({scroll:document.querySelector('#panel').scrollLeft,focused:document.activeElement.id})),{scroll:0,focused:'last'});assert.equal(result.implicit_focus_scrolling_suspended,true);
 const audit=await new(require('@axe-core/playwright').default)({page}).analyze();assert.ok(Array.isArray(audit.violations));assert.equal(await page.evaluate(()=>document.querySelector('#panel').scrollLeft),0);
 }finally{await browser.close();}
});

test('SVG SMIL rotation retains authored elements and pauses the acquired timeline',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();await require('../measurement_state').install(page);
 await page.route('https://svg-state.example/',r=>r.fulfill({contentType:'text/html',body:'<html><body><svg width="80" height="80"><path d="M10 10L60 60"><animateTransform attributeName="transform" type="rotate" from="0 40 40" to="360 40 40" dur="0.5s" repeatCount="indefinite"/></path></svg></body></html>'}));
 await page.goto('https://svg-state.example/');await page.waitForTimeout(80);const result=await require('../measurement_state').freeze(page);
 const before=await page.locator('path').evaluate(e=>getComputedStyle(e).transform);await page.waitForTimeout(180);
 assert.equal(await page.locator('path').evaluate(e=>getComputedStyle(e).transform),before);
 assert.equal(await page.locator('animateTransform').count(),1);assert.equal(result.svg_animations_suspended,true);
 assert.equal(await page.locator('svg').evaluate(e=>e.animationsPaused()),true);
 }finally{await browser.close();}
});
