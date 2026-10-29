'use strict';
const VERSION='native-media-progression-pause-v1';
// One implementation is used before native navigation and immediately after
// document.write, which removes listeners installed on the initial document.
function observe(){
 const records=new WeakMap();let events=0;
 document.addEventListener('playing',event=>{
  const element=event.target;
  if(!(element instanceof HTMLMediaElement))return;
  queueMicrotask(()=>{
   // Observe native state after authored listeners. Never synthesize play
   // results, force a position, or replace the media's source/attributes.
   if(!element.isConnected||element.ownerDocument!==document||element.paused||element.ended)return;
   const first=records.get(element);element.pause();events++;
   records.set(element,{events:(first?.events||0)+1,first_time:first?.first_time??element.currentTime,last_time:element.currentTime,ready_state:element.readyState});
  });
 },true);
 Object.defineProperty(window,'__a11yHarnessNativeMediaPause',{configurable:true,value:Object.freeze({version:'native-media-progression-pause-v1',snapshot:()=>({version:'native-media-progression-pause-v1',events,media:Array.from(document.querySelectorAll('video,audio'),e=>records.get(e)||null)})})});
}
async function install(page){await page.addInitScript(observe);}
// The generated function contains only this trusted shared observer. HTML is
// passed separately as a browser argument, never interpolated into code.
const writeDocument=new Function('documentHtml','window.stop();document.open();document.write(documentHtml);document.close();('+observe.toString()+')();');
async function write(page,html){await page.evaluate(writeDocument,html);}
async function snapshot(page){return page.evaluate(()=>window.__a11yHarnessNativeMediaPause?.snapshot()||null);}
module.exports={VERSION,install,write,snapshot};
