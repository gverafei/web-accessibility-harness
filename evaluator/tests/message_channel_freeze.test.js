const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),measurement=require('../measurement_state');
test('native MessageChannel callbacks run before freeze and are gated afterwards on both open ports',async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage();await measurement.install(page);
  await page.goto('data:text/html,<main>Acquired state</main>');
  await page.evaluate(()=>{window.events=[];window.channel=new MessageChannel();channel.port1.onmessage=e=>events.push('property:'+e.data);channel.port2.addEventListener('message',e=>events.push('listener:'+e.data));channel.port2.start();channel.port1.postMessage('before');channel.port2.postMessage('before');});
  await page.waitForFunction(()=>events.length===2);assert.deepEqual((await page.evaluate(()=>events)).sort(),['listener:before','property:before']);
  const receipt=await measurement.freeze(page);assert.equal(receipt.message_channels,1);assert.equal(receipt.message_channel_callbacks_suspended,true);
  const html=await page.content();await page.evaluate(()=>{channel.port1.postMessage('after');channel.port2.postMessage('after');});await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>events.length),2);assert.equal(await page.content(),html);assert.equal(await page.evaluate(()=>channel instanceof MessageChannel&&channel.port1 instanceof MessagePort),true);
  await page.evaluate(()=>{window.later=new MessageChannel();later.port1.onmessage=()=>document.querySelector('main').textContent='Late scheduler mutation';later.port2.postMessage('late');});await page.waitForTimeout(100);assert.equal(await page.content(),html);
 }finally{await browser.close();}
});
