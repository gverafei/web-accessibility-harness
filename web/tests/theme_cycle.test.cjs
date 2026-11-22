const {test} = require('node:test');
const assert = require('node:assert/strict');
const {init, nextTheme} = require('../app/static/js/theme_cycle.js');
function fixture(fetch) {
    const icons = ['dark','light','system'].map(themeIcon => ({dataset:{themeIcon},hidden:true,
        toggleAttribute(_,value){this.hidden=value}}));
    const attrs = {}, events = {}, media = {matches:false,addEventListener:(_, fn)=>{events.media=fn}};
    const button = {dataset:{label:'Color theme',labelLight:'Light',labelDark:'Dark',labelSystem:'System',
        urlLight:'/theme/light',urlDark:'/theme/dark',urlSystem:'/theme/system',error:'Save failed'},
        disabled:false,querySelectorAll:()=>icons,addEventListener:(_,fn)=>{events.click=fn},
        setAttribute:(k,v)=>{attrs[k]=v},removeAttribute:k=>{delete attrs[k]}};
    const status = {textContent:''}, html = {dataset:{theme:'dark',themeChoice:'dark'}};
    let calls = [], updates = [];
    const chart = {options:{plugins:{legend:{labels:{}}},scales:{x:{ticks:{},grid:{},title:{},border:{}}}},update:mode=>updates.push(mode)};
    const env = {document:{documentElement:html,getElementById:id=>id==='themeCycle'?button:status},
        matchMedia:()=>media,Chart:{defaults:{},instances:{a:chart}},
        fetch:async (...args)=>{calls.push(args);return fetch ? fetch(...args) :
            {ok:true,json:async()=>({theme:nextTheme(html.dataset.themeChoice)})}}};
    return {control:init(env),html,button,status,icons,attrs,events,media,calls,updates,chart};
}
test('cycle order and selected icon stay in sync without navigation',async()=>{
    const f=fixture();
    for(const theme of ['light','system','dark']){
        await f.control.cycle();
        assert.equal(f.html.dataset.themeChoice,theme);
        assert.deepEqual(f.icons.filter(i=>!i.hidden).map(i=>i.dataset.themeIcon),[theme]);
        assert.match(f.attrs['aria-label'],new RegExp(nextTheme(theme)==='system'?'System':nextTheme(theme)[0].toUpperCase()+nextTheme(theme).slice(1)));
        assert.equal(f.button.disabled,false);
    }
    assert.equal(f.calls[0][0],'/theme/light');
    assert.equal(f.calls[0][1].method,'POST');
    assert.equal(f.calls[0][1].credentials,'same-origin');
    assert.equal(f.chart.options.scales.x.ticks.color,'#cbd5e1');
    assert.equal(f.chart.options.scales.x.title.color,'#cbd5e1');
});
test('system follows OS only while system mode is selected',async()=>{
    const f=fixture(); await f.control.cycle(); await f.control.cycle();
    f.media.matches=true; f.events.media();
    assert.equal(f.html.dataset.theme,'dark');
    await f.control.cycle(); await f.control.cycle();
    f.events.media(); assert.equal(f.html.dataset.theme,'light');
});
test('failed save retains current choice and announces retry, no stuck button',async()=>{
    for(const fetch of [async()=>({ok:false}),async()=>{throw Error('offline')},async()=>({ok:true,json:async()=>({theme:'wrong'})})]) {
        const f=fixture(fetch); await f.control.cycle();
        assert.equal(f.html.dataset.themeChoice,'dark');
        assert.equal(f.status.textContent,'Save failed');
        assert.equal(f.button.disabled,false);
        assert.equal(f.attrs['aria-busy'],undefined);
    }
});
test('pending save ignores a repeated click',async()=>{
    let resolve; const f=fixture(()=>new Promise(done=>{resolve=done}));
    const pending=f.control.cycle(); await f.control.cycle();
    assert.equal(f.calls.length,1);
    resolve({ok:true,json:async()=>({theme:'light'})}); await pending;
    assert.equal(f.html.dataset.themeChoice,'light');
});
