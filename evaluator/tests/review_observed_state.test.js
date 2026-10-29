const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const runtime = fs.readFileSync(require('node:path').resolve(__dirname, '../../web/app/static/js/observed_state.js'), 'utf8');

test('saved effects and the selected fade slide survive a different viewport', async () => {
    const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
    try {
        const page = await browser.newPage({viewport:{width:600,height:600}});
        await page.setContent(`<style>
            body{margin:0} #viewport{overflow:hidden} #track{display:flex}
            .slide{flex:0 0 100%} .title{opacity:0;animation:enter 250ms linear 50ms forwards;animation-play-state:paused}
            @keyframes enter{from{opacity:0;transform:translateY(50%)}to{opacity:1;transform:translateY(0)}}
            </style><div id="viewport"><div id="track">
            <div class="slide" style="opacity:0;pointer-events:none;transform:translateX(1500px)">First</div>
            <div class="slide" style="opacity:1;pointer-events:auto;transform:translateX(-1500px)"><p class="title">Saved product</p></div>
            </div></div><p id="unobserved" style="opacity:0">Keep hidden</p>`);
        const reference = await page.evaluate(() => {
            const a = document.querySelector('.title').getAnimations()[0];
            return {version:'observed-css-animation-state-v1',path:'html > body:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > p:nth-of-type(1)',
                name:a.animationName,paused:true,pseudo:null,time:300,keyframes:a.effect.getKeyframes(),timing:a.effect.getTiming()};
        });
        const state = {animations:[reference],carousels:[{path:'html > body:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1)',count:2,active:1}]};
        await page.addScriptTag({content:`const r=document.createElement('script');r.type='application/json';r.dataset.harnessObservedState='fixture';r.textContent=${JSON.stringify(JSON.stringify(state))};document.body.append(r);`});
        await page.addScriptTag({content:runtime});
        const observe = () => page.evaluate(() => ({opacity:getComputedStyle(document.querySelector('.title')).opacity,
            hidden:getComputedStyle(document.querySelector('#unobserved')).opacity,
            left:document.querySelectorAll('.slide')[1].getBoundingClientRect().left,
            state:document.querySelector('[data-harness-observed-state]').dataset}));
        let result=await observe();
        assert.equal(result.opacity,'1');assert.equal(result.hidden,'0');assert.equal(result.left,0);
        assert.equal(result.state.restoredAnimations,'1');assert.equal(result.state.alignedCarousels,'1');
        await page.setViewportSize({width:1100,height:700});
        result=await observe();assert.equal(result.left,0);assert.equal(result.opacity,'1');
        // An altered candidate effect is not overridden by the source's effect.
        await page.addStyleTag({content:'.title{animation-duration:500ms}'});
        await page.evaluate(() => document.querySelector('.title').getAnimations()[0].currentTime=0);
        await page.addScriptTag({content:runtime});
        result=await observe();assert.equal(result.state.restoredAnimations,'0');assert.equal(result.opacity,'0');
        await page.close();
    } finally { await browser.close(); }
});

test('saved slide buttons work with mouse and keyboard without publisher requests', async () => {
    const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
    try {
        const page = await browser.newPage({viewport:{width:800,height:600}});
        let requests = 0;
        page.on('request', () => requests++);
        await page.setContent(`<style>body{margin:0} #viewport{overflow:hidden} #track{display:flex}.slide{flex:0 0 100%}</style>
            <div id="viewport" x-ref="embla"><div id="track">
            <div class="slide" style="opacity:0;pointer-events:none;transform:translateX(1500px)"><h2>First saved product</h2></div>
            <div class="slide" style="opacity:1;pointer-events:auto;transform:translateX(-1500px)"><h2>Second saved product</h2></div>
            </div><button @click="emblaCarousel.scrollTo(0)" :class="{ 'font-bold': activeDot === 0, 'opacity-50': activeDot !== 0 }">First</button>
            <button @click="emblaCarousel.scrollTo(1)" :class="{ 'font-bold': activeDot === 1, 'opacity-50': activeDot !== 1 }">Second</button>
            <button @click="fetch('https://unrecorded.test/')">Unrelated</button></div>`);
        const base = 'html > body:nth-of-type(1) > div:nth-of-type(1)';
        const state = {animations:[],carousels:[{path:base+' > div:nth-of-type(1)',count:2,active:1,
            controls:[0,1].map(index=>({path:base+` > button:nth-of-type(${index+1})`,index,action:`emblaCarousel.scrollTo(${index})`}))}]};
        await page.addScriptTag({content:`const r=document.createElement('script');r.type='application/json';r.dataset.harnessObservedState='fixture';r.textContent=${JSON.stringify(JSON.stringify(state))};document.body.append(r);`});
        await page.addScriptTag({content:runtime});
        const selection = () => page.evaluate(() => ({current:document.querySelector('#track').dataset.harnessCurrentSlide,
            opacities:[...document.querySelectorAll('.slide')].map(s=>s.style.opacity),
            interactions:document.querySelector('[data-harness-observed-state]').dataset.slideInteractions || '0'}));
        assert.deepEqual(await selection(),{current:'1',opacities:['0','1'],interactions:'0'});
        await page.getByRole('button',{name:'First',exact:true}).click();
        assert.deepEqual(await selection(),{current:'0',opacities:['1','0'],interactions:'1'});
        await page.getByRole('button',{name:'Second',exact:true}).press('Enter');
        assert.deepEqual(await selection(),{current:'1',opacities:['0','1'],interactions:'2'});
        await page.getByRole('button',{name:'First',exact:true}).press('Space');
        assert.deepEqual(await selection(),{current:'0',opacities:['1','0'],interactions:'3'});
        await page.getByRole('button',{name:'Unrelated',exact:true}).click();
        assert.equal(requests,0);
        assert.equal((await selection()).current,'0');
        await page.close();
    } finally { await browser.close(); }
});
