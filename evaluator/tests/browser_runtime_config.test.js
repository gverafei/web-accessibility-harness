const test=require('node:test'),assert=require('node:assert/strict');
const {browserRuntimeConfig}=require('../run_axe_isolated'),{loadPolicy}=require('../run_axe');
test('browser child receives the same browser policy without provider, WAVE or unknown settings',()=>{
 const source={page_load_timeout_ms:'12000',axe_hard_timeout_ms:'12345',network_idle_timeout_ms:'500',page_settle_delay_ms:'100',dom_stability_window_ms:'200',dom_stability_timeout_ms:'900',enable_lazy_load_scroll:'false',scroll_step_px:'80',scroll_delay_ms:'15',max_scroll_steps:'10',openrouter_api_key:'private-provider-sentinel',wave_api_key:'private-wave-sentinel',unknown_secret:'private-extra-sentinel'};
 const clean=browserRuntimeConfig(source);assert.deepEqual(loadPolicy(clean),loadPolicy(source));
 assert.equal(Object.keys(clean).length,10);assert.equal(JSON.stringify(clean).includes('private-'),false);assert.equal(source.openrouter_api_key,'private-provider-sentinel');
 assert.deepEqual(browserRuntimeConfig(),{});
});
