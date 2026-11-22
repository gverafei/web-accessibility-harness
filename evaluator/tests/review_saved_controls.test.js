const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright');
const scripts = path.resolve(__dirname,'../../web/app/static/js');
const launch = () => chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});

test('saved complete video restores its observed frame without autoplay or publisher access',async()=>{
    const browser=await launch();
    try {
        const page=await browser.newPage();
        await page.goto('about:blank');
        const bytes=Buffer.from(await page.evaluate(async()=>{
            const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;
            const context=canvas.getContext('2d');context.fillStyle='green';context.fillRect(0,0,32,32);
            const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),parts=[];
            const frames=setInterval(()=>context.fillRect(0,0,32,32),50);
            recorder.ondataavailable=event=>parts.push(event.data);
            const stopped=new Promise(resolve=>recorder.onstop=resolve);
            recorder.start();await new Promise(resolve=>setTimeout(resolve,400));
            context.fillStyle='blue';context.fillRect(0,0,32,32);await new Promise(resolve=>setTimeout(resolve,500));
            clearInterval(frames);recorder.stop();await stopped;stream.getTracks().forEach(track=>track.stop());
            return [...new Uint8Array(await new Blob(parts).arrayBuffer())];
        }));
        const sha256=crypto.createHash('sha256').update(bytes).digest('hex');
        const requests=[];
        await page.route('https://saved.test/**',route=>{
            requests.push(route.request().url());
            if(route.request().url().endsWith('/page.html')) return route.fulfill({contentType:'text/html',body:`<html><body><section class="b-hero"><video class="b-hero__bg-video" preload="none" muted><source src="assets/${sha256}" type="video/webm"></video><button data-js="video-trigger" aria-label="Pause the video">Toggle</button></section></body></html>`});
            if(route.request().url().endsWith('/'+sha256)) {
                const response=require('../frozen_media').response({mime:'video/webm',body:bytes,headers:{}},route.request().headers().range);
                return route.fulfill({status:response.status,headers:response.headers,body:response.body});
            }
            return route.abort();
        });
        await page.goto('https://saved.test/page.html');
        await page.evaluate(()=>{
            window.mediaEvents=[];
            const video=document.querySelector('video');
            for(const event of ['loadedmetadata','loadeddata','seeking','seeked','error']) video.addEventListener(event,()=>window.mediaEvents.push({event,time:video.currentTime,duration:video.duration,ready:video.readyState}));
        });
        const media={path:'html > body:nth-of-type(1) > section:nth-of-type(1) > video:nth-of-type(1)',
            time:0.65,sha256,width:32,height:32,control:'html > body:nth-of-type(1) > section:nth-of-type(1) > button:nth-of-type(1)',
            binding_sha256:'fdf88d0ffda34c9202f164105f2965d3d30b2f3ffe773c9bc78a8abce0096132'};
        await page.evaluate(state=>{
            const record=document.createElement('script');record.type='application/json';record.dataset.harnessObservedState='fixture';
            record.textContent=JSON.stringify(state);document.body.append(record);
        },{animations:[],carousels:[],media:[media]});
        await page.addScriptTag({content:fs.readFileSync(path.join(scripts,'observed_state.js'),'utf8')});
        try {
            await page.waitForFunction(()=>document.querySelector('[data-harness-observed-state]').dataset.restoredMedia==='1',null,{timeout:5000});
        } catch(error) {
            console.error(await page.evaluate(()=>{const v=document.querySelector('video');return {events:window.mediaEvents,ready:v.readyState,time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight,error:v.error?.message,src:v.currentSrc,state:document.querySelector('[data-harness-observed-state]').dataset};}));
            throw error;
        }
        const frame=await page.evaluate(()=>{
            const video=document.querySelector('video'),canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;
            const context=canvas.getContext('2d');context.drawImage(video,0,0);
            return {paused:video.paused,time:video.currentTime,pixel:[...context.getImageData(16,16,1,1).data]};
        });
        assert.equal(frame.paused,true);assert.ok(Math.abs(frame.time-0.65)<0.03);
        assert.ok(frame.pixel[2]>150 && frame.pixel[0]<50,'restores the saved blue frame instead of a black surface');
        await page.getByRole('button',{name:'Play the video'}).click();
        await page.waitForFunction(()=>!document.querySelector('video').paused);
        await page.getByRole('button',{name:'Pause the video'}).press('Enter');
        assert.equal(await page.locator('video').evaluate(video=>video.paused),true);
        assert.ok(requests.every(url=>url==='https://saved.test/page.html'||url==='https://saved.test/assets/'+sha256));
    } finally {await browser.close();}
});

test('captured navigation opens saved panels with keyboard and restores them on close',async()=>{
    const browser=await launch();
    try {
        const page=await browser.newPage({viewport:{width:1200,height:800}});
        let requests=0;page.on('request',()=>requests++);
        await page.setContent(`<html><body><header data-js="site-header">
          <button id="open" aria-controls="site-nav">Menu</button><button id="close" aria-controls="site-nav">Close</button>
          <div id="site-nav" aria-hidden="true"><nav>
          <div class="nav-primary__col-0"><div id="group"><button id="trigger" class="nav-primary__action--depth-0" aria-controls="child">Academics</button>
          <div id="child" aria-labelledby="trigger" aria-hidden="true"><button id="back" aria-controls="child">Back</button><a href="https://publisher.test/academics">Existing link</a></div></div></div>
          <div class="nav-primary__col-1"></div></nav></div></header></body></html>`);
        const base='html > body:nth-of-type(1) > header:nth-of-type(1)';
        const state={navigation:[{header:base,panel:base+' > div:nth-of-type(1)',nav:base+' > div:nth-of-type(1) > nav:nth-of-type(1)',
          open:base+' > button:nth-of-type(1)',close:base+' > button:nth-of-type(2)',
          children:[{trigger:base+' > div:nth-of-type(1) > nav:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > button:nth-of-type(1)',
            panel:base+' > div:nth-of-type(1) > nav:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1)',
            back:base+' > div:nth-of-type(1) > nav:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(1) > button:nth-of-type(1)',depth:0}],
          binding_sha256:'c944a9e17a7f5b32a52eaab8ffafa992c6e7cd8bd9563a5cc4d6ba78f4f0d8ba',
          stylesheet_sha256:'0e203130cf01c6710373046614ae8356614e5f4bd7bef03c5f38a7bbcf1e79d9'}]};
        await page.evaluate(state=>{const r=document.createElement('script');r.type='application/json';r.dataset.harnessObservedState='fixture';r.textContent=JSON.stringify(state);document.body.append(r);},state);
        await page.addScriptTag({content:fs.readFileSync(path.join(scripts,'saved_navigation.js'),'utf8')});
        assert.equal(await page.locator('#site-nav').getAttribute('aria-hidden'),'true');
        await page.locator('#open').press('Enter');
        assert.equal(await page.locator('#site-nav').getAttribute('aria-hidden'),'false');
        await page.locator('#trigger').press('Space');
        assert.equal(await page.locator('#child').getAttribute('aria-hidden'),'false');
        assert.equal(await page.locator('#child').evaluate(node=>node.parentElement.className),'nav-primary__col-1 nav-primary__col--rendered');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#child').getAttribute('aria-hidden'),'true');
        assert.equal(await page.locator('#child').evaluate(node=>node.parentElement.id),'group');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#open').getAttribute('aria-expanded'),'false');
        assert.equal(await page.locator('a').getAttribute('href'),'https://publisher.test/academics');
        await page.setViewportSize({width:400,height:700});
        await page.locator('#open').click();await page.locator('#trigger').click();
        assert.equal(await page.locator('#child').evaluate(node=>node.parentElement.id),'group');
        await page.locator('#back').click();await page.locator('#close').click();
        assert.equal(await page.locator('#site-nav').getAttribute('aria-hidden'),'true');
        assert.equal(requests,0);
    } finally {await browser.close();}
});
