const test=require('node:test'),assert=require('node:assert/strict');
const {contextOptions,lighthouseFlags,viewport}=require('../desktop_profile');
test('desktop context and Lighthouse share dimensions without mobile emulation',()=>{
 assert.deepEqual(viewport,{width:1440,height:1000});
 assert.equal(contextOptions().isMobile,false);
 const flags=lighthouseFlags();assert.equal(flags.formFactor,'desktop');assert.equal(flags.screenEmulation.mobile,false);
 assert.equal(flags.screenEmulation.width,viewport.width);assert.equal(flags.screenEmulation.height,viewport.height);
 assert.equal(lighthouseFlags(true).screenEmulation.disabled,true);assert.equal(lighthouseFlags(true).disableFullPageScreenshot,true);
 const first=contextOptions();first.viewport.width=1;assert.equal(contextOptions().viewport.width,1440);
});
