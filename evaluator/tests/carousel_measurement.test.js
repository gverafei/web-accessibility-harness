const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
test('carousel measurement leaves authored lookalike controls and content untouched without a library instance',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();
  await page.setContent('<main><div class="caroufredsel_wrapper"><section><button aria-pressed="true">Current</button><p>Retain this content</p></section></div></main>');
  const before=await page.content(),result=await require('../carousel_measurement').prepare(page);
  assert.deepEqual(result.widgets,[]);assert.equal(await page.content(),before);
 }finally{await browser.close();}
});
