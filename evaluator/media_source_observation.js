'use strict';
const VERSION='observed-media-source-v1';
function observe(){
 const key=Symbol.for('a11yharness.mediaSourceObservation');if(window[key])return;
 const original=URL.createObjectURL,objects=new Map();
 URL.createObjectURL=function(...args){
  const url=Reflect.apply(original,this,args),source=args[0];
  if(typeof MediaSource!=='undefined'&&source instanceof MediaSource){
   if(objects.size>=256)objects.delete(objects.keys().next().value);
   objects.set(url,new WeakRef(source));
  }
  return url;
 };
 Object.defineProperty(window,key,{value:url=>{
  const source=objects.get(url)?.deref();if(!source)return null;
  return {version:'observed-media-source-v1',ready_state:source.readyState,buffers:source.sourceBuffers.length,active_buffers:source.activeSourceBuffers.length};
 }});
}
async function install(page){await page.addInitScript(observe);}
module.exports={VERSION,observe,install};
