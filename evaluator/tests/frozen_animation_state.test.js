const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),state=require('../frozen_animation_state');
test('paused acquired CSS animation time restores actual visibility without changing HTML',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();const html='<html><head><style>@keyframes reveal{from{opacity:0}to{opacity:1}}#panel{animation:reveal 1s linear forwards paused}</style></head><body><div id="panel"><img alt="Example" src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%222%22 height=%222%22/%3E"></div></body></html>';
 await page.setContent(html);await page.evaluate(()=>document.getAnimations()[0].currentTime=500);const refs=await state.capture(page);assert.equal(refs[0].time,500);
 await page.setContent(html);const before=await page.content();assert.equal(await page.locator('#panel').evaluate(e=>getComputedStyle(e).opacity),'0');
 const stored=JSON.parse(JSON.stringify(refs));stored[0].timing=Object.fromEntries(Object.entries(stored[0].timing).reverse());assert.equal((await state.restore(page,stored)).results[0].status,'restored');assert.equal(await page.locator('#panel').evaluate(e=>getComputedStyle(e).opacity),'0.5');assert.equal(await page.content(),before);
 await page.waitForTimeout(50);assert.equal(await page.locator('#panel').evaluate(e=>getComputedStyle(e).opacity),'0.5');assert.equal((await state.restore(page,refs)).results[0].time,500);
 await page.setContent(html.replace('to{opacity:1}','to{opacity:.8}'));assert.equal((await state.restore(page,refs)).results[0].status,'unmatched_reference');assert.equal(await page.locator('#panel').evaluate(e=>getComputedStyle(e).opacity),'0');
 assert.equal((await state.restore(page,[])).eligible,0);assert.equal((await state.restore(page,refs.map(r=>({...r,time:null})))).eligible,0);assert.equal((await state.restore(page,refs.map(r=>({...r,path:'body *'})))).eligible,0);
 await page.setContent(html);assert.ok((await state.restore(page,[...refs,...refs])).results.every(r=>r.status==='unmatched_reference'));
 }finally{await browser.close();}
});
test('non-document and non-CSS animation state is not fabricated as a numeric paused timeline',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();await page.setContent('<style>@keyframes show{from{opacity:0}to{opacity:1}}p{animation:show 1s;animation-timeline:scroll(root block)}</style><p>Scroll</p>');assert.equal((await state.capture(page)).length,0);
 await page.setContent('<p>Script animation</p>');await page.evaluate(()=>document.querySelector('p').animate([{opacity:0},{opacity:1}],1000).pause());assert.equal((await state.capture(page)).length,0);
 }finally{await browser.close();}
});
