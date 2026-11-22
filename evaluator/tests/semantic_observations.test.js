'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),{chromium}=require('playwright'),{collect}=require('../semantic_observations');
test('readonly states bind exact DOM, native properties, unique controlled visibility and validity',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.route('**/*',r=>r.abort());
 await page.setContent('<input type="checkbox" aria-checked="true"><button aria-expanded="true" aria-controls="panel">Details</button><div id="panel" hidden>Hidden</div><input type="email" required aria-errormessage="error"><p id="error">Enter email</p>');
 const before=await page.content();const x=await collect(page);assert.equal(await page.content(),before);assert.equal(x.elements.length,3);assert.equal(x.elements[0].checked,false);assert.equal(x.elements[1].controlled[0].visible,false);assert.equal(x.elements[2].validity.valueMissing,true);
 for(const e of x.elements)assert.equal(await page.locator(e.selector).count(),1);
 }finally{await browser.close();}
});
