const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),AxeBuilder=require('@axe-core/playwright').default;
const catalog=require('../../web/app/accessibility_taxonomy/catalog.json');
test('syntactic and layout counts respond to known repairs on the same desktop document',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();
  const counts=[];
  for(const repaired of [false,true]){
   await page.setContent(`<html ${repaired?'lang="en"':''}><head><title>Accessibility measurement control</title></head><body><main><h1>Measurement control</h1><p style="font-size:16px;color:${repaired?'#111':'#aaa'};background:#fff">Text contrast should improve after this repair.</p><img ${repaired?'alt="A red square"':''} width="80" height="80" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect width='80' height='80' fill='red'/%3E%3C/svg%3E"></main></body></html>`);
   const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze();
   const totals={Syntactic:0,Layout:0};
   for(const violation of audit.violations){const rule=catalog.violations.find(r=>r.id===violation.id);if(rule&&rule.category in totals)totals[rule.category]+=violation.nodes.length;}
   counts.push(totals);
   assert.deepEqual(page.viewportSize(),{width:1440,height:1000});
  }
  assert.ok(counts[0].Syntactic>=2);assert.ok(counts[0].Layout>=1);
  assert.deepEqual(counts[1],{Syntactic:0,Layout:0});
 }finally{await browser.close();}
});
