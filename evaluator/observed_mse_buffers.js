'use strict';
const crypto=require('node:crypto');
const VERSION='observed-mse-buffer-bytes-v1';
const MAX_BYTES=8000000;
// A passive, bounded recorder for native acquisition.
// Byte sequences are browser-derived evidence, not replacements for HTTP assets.
function observe({maxBytes}){
 const key=Symbol.for('a11yharness.mseBufferBytes');if(window[key])return;
 const sources=new WeakMap(),buffers=new WeakMap(),urls=new Map();let total=0;
 const reject=(record,reason)=>{if(record&&!record.reasons.includes(reason))record.reasons.push(reason);};
 const create=URL.createObjectURL;
 URL.createObjectURL=function(...args){
  const url=Reflect.apply(create,this,args),source=args[0];
  if(typeof MediaSource!=='undefined'&&source instanceof MediaSource){
   if(urls.size>=32)return url;
   const record=sources.get(source)||{source,buffers:[],reasons:[]};sources.set(source,record);urls.set(url,record);
  }return url;
 };
 if(typeof MediaSource!=='undefined'){
  const add=MediaSource.prototype.addSourceBuffer;
  MediaSource.prototype.addSourceBuffer=function(...args){
   const buffer=Reflect.apply(add,this,args),record=sources.get(this)||{source:this,buffers:[],reasons:[]};sources.set(this,record);
   if(record){
    if(record.buffers.length>=8){reject(record,'source_buffer_limit');return buffer;}
    if(typeof args[0]!=='string')reject(record,'unobservable_codec');
    const entry={codec:typeof args[0]==='string'?args[0]:null,buffer,appends:[]};record.buffers.push(entry);buffers.set(buffer,{record,entry});
    buffer.addEventListener('error',()=>reject(record,'source_buffer_error'));
    buffer.addEventListener('abort',()=>reject(record,'source_buffer_abort'));
   }return buffer;
  };
  const remove=MediaSource.prototype.removeSourceBuffer;
  MediaSource.prototype.removeSourceBuffer=function(...args){const result=Reflect.apply(remove,this,args);reject(sources.get(this),'removed_source_buffer');return result;};
 }
 if(typeof SourceBuffer!=='undefined'){
  const append=SourceBuffer.prototype.appendBuffer;
  SourceBuffer.prototype.appendBuffer=function(...args){
   const tracked=buffers.get(this);let saved=null,reason=null;
   if(tracked&&!tracked.record.reasons.length){
    const value=args[0];
    try{
     const bytes=ArrayBuffer.isView(value)?new Uint8Array(value.buffer,value.byteOffset,value.byteLength):value instanceof ArrayBuffer?new Uint8Array(value):null;
     if(!bytes)reason='unobservable_buffer';
     else if(tracked.entry.appends.length>=256)reason='append_limit';
     else if(total+bytes.byteLength>maxBytes)reason='byte_limit';
     else saved={bytes:bytes.slice(),mode:this.mode,timestamp_offset:this.timestampOffset,append_window_start:this.appendWindowStart,append_window_end:Number.isFinite(this.appendWindowEnd)?this.appendWindowEnd:null};
    }catch{reason='unobservable_buffer';}
   }
   // Native behavior and native exceptions have precedence over observation.
   const result=Reflect.apply(append,this,args);
   if(tracked){if(reason)reject(tracked.record,reason);if(saved){tracked.entry.appends.push(saved);total+=saved.bytes.byteLength;}}
   return result;
  };
  for(const name of ['remove','abort','changeType']){
   const original=SourceBuffer.prototype[name];if(!original)continue;
   SourceBuffer.prototype[name]=function(...args){const result=Reflect.apply(original,this,args);reject(buffers.get(this)?.record,'unsupported_'+name);return result;};
  }
 }
 Object.defineProperty(window,key,{value:()=>{
  const base64=bytes=>{let result='';for(let i=0;i<bytes.length;i+=4096)result+=String.fromCharCode(...bytes.subarray(i,i+4096));return btoa(result);};
  const unique=new Map();for(const [url,r]of urls){const previous=unique.get(r);if(previous)previous.aliases.push(url);else unique.set(r,{url,aliases:[url],record:r});}
  return {version:'observed-mse-buffer-bytes-v1',scope:'window_media_source_only',total_bytes:total,max_bytes:maxBytes,records:[...unique.values()].map(({url,aliases,record:r})=>({url,aliases,ready_state:r.source.readyState,duration:Number.isFinite(r.source.duration)?r.source.duration:null,reasons:[...r.reasons],buffers:r.buffers.map(e=>({codec:e.codec,updating:e.buffer.updating,appends:e.appends.map(a=>({...a,bytes:undefined,body:base64(a.bytes)}))}))}))};
 }});
}
async function install(page,{maxBytes=MAX_BYTES}={}){
 if(!Number.isSafeInteger(maxBytes)||maxBytes<1||maxBytes>MAX_BYTES)throw Error('Invalid MSE observation byte limit');
 await page.addInitScript(observe,{maxBytes});
}
async function capture(page){
 const result=await page.evaluate(()=>window[Symbol.for('a11yharness.mseBufferBytes')]?.()||null);
 if(!result)return null;
 for(const record of result.records)for(const buffer of record.buffers)for(const append of buffer.appends){
  const bytes=Buffer.from(append.body,'base64');append.byte_length=bytes.length;append.sha256=crypto.createHash('sha256').update(bytes).digest('hex');
 }
 return result;
}
function validate(record){
 if(!record||!Array.isArray(record.reasons)||record.reasons.length||!Array.isArray(record.buffers)||!record.buffers.length||record.buffers.length>8||!['open','ended'].includes(record.ready_state))throw Error('Incomplete MSE byte evidence');
 if(!(record.duration===null||Number.isFinite(record.duration)&&record.duration>=0))throw Error('Invalid observed MSE duration');
 let total=0;
 for(const buffer of record.buffers){
  if(typeof buffer.codec!=='string'||buffer.codec.length>512||buffer.updating||!Array.isArray(buffer.appends)||!buffer.appends.length||buffer.appends.length>256)throw Error('Incomplete MSE buffer');
  for(const a of buffer.appends){
   if(typeof a.body!=='string'||a.body.length>Math.ceil(MAX_BYTES/3)*4||!Number.isSafeInteger(a.byte_length)||a.byte_length<1||!['segments','sequence'].includes(a.mode)||!Number.isFinite(a.timestamp_offset)||!Number.isFinite(a.append_window_start)||a.append_window_start<0||!(a.append_window_end===null||Number.isFinite(a.append_window_end)&&a.append_window_end>a.append_window_start))throw Error('Invalid MSE append evidence');
   const bytes=Buffer.from(a.body,'base64');total+=bytes.length;
   if(total>MAX_BYTES||bytes.toString('base64')!==a.body||bytes.length!==a.byte_length||crypto.createHash('sha256').update(bytes).digest('hex')!==a.sha256)throw Error('Invalid MSE checksum or size');
  }
 }
 return total;
}
async function restore(page,path,record,time,{budgetMs=15000}={}){
 validate(record);
 if(typeof path!=='string'||!/^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9][0-9]*\))+$/.test(path)||!Number.isFinite(time)||time<0||!Number.isSafeInteger(budgetMs)||budgetMs<1||budgetMs>15000)throw Error('Invalid MSE restoration target');
 // The caller verifies native element identity and the shared resource budget.
 return page.evaluate(async({path,record,time,budgetMs})=>{
  const video=document.querySelector(path);if(!video||!['VIDEO','AUDIO'].includes(video.tagName))return {status:'unmatched_reference'};
  if(!record.buffers.every(b=>MediaSource.isTypeSupported(b.codec)))return {status:'unsupported_codec'};
  const originalSrc=video.getAttribute('src'),preload=video.getAttribute('preload'),source=new MediaSource(),url=URL.createObjectURL(source),deadline=Date.now()+budgetMs;
  const wait=async(predicate)=>{while(Date.now()<deadline&&!predicate())await new Promise(resolve=>setTimeout(resolve,25));if(!predicate())throw Error('Observed MSE state did not settle');};
  try{
   video.pause();video.preload='auto';video.src=url;
   await wait(()=>source.readyState==='open');
   const decoders=record.buffers.map(b=>source.addSourceBuffer(b.codec));
   for(let index=0;index<record.buffers.length;index++){
    const b=record.buffers[index],buffer=decoders[index];let error=false;buffer.addEventListener('error',()=>{error=true;});buffer.addEventListener('abort',()=>{error=true;});
    for(const a of b.appends){
     buffer.mode=a.mode;buffer.timestampOffset=a.timestamp_offset;
     // Set end first when necessary, so a legitimate acquired window can be
     // reproduced without a transient invalid start >= current end.
     const end=a.append_window_end===null?Infinity:a.append_window_end;
     if(a.append_window_start>=buffer.appendWindowEnd)buffer.appendWindowEnd=end;
     buffer.appendWindowStart=a.append_window_start;buffer.appendWindowEnd=end;
     const binary=atob(a.body),bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));buffer.appendBuffer(bytes);
     await wait(()=>!buffer.updating||error);if(error)throw Error('Recorded MSE bytes did not decode');
    }
   }
   if(record.duration!==null){if(!Number.isFinite(record.duration)||record.duration<0)throw Error('Invalid observed MSE duration');source.duration=record.duration;}
   if(record.ready_state==='ended')source.endOfStream();
   await wait(()=>video.readyState>=2||video.error);if(video.error)throw Error('Recorded MSE media failed');
   video.currentTime=time;await wait(()=>!video.seeking&&video.readyState>=2&&Math.abs(video.currentTime-time)<=0.01);video.pause();
   return {status:'restored',scope:'actual_decoder_frame_only',original_src:originalSrc,current_src:video.currentSrc,current_time:video.currentTime,ready_state:video.readyState,video_width:video.videoWidth||0,video_height:video.videoHeight||0,live_resources:false};
  }catch(error){URL.revokeObjectURL(url);return {status:'failed',reason:error.message};}
  finally{if(preload===null)video.removeAttribute('preload');else video.setAttribute('preload',preload);}
 },{path,record,time,budgetMs});
}
module.exports={VERSION,MAX_BYTES,observe,install,capture,validate,restore};

async function reference(page,visible){
 const captured=await capture(page),records=[],targets=[],diagnostics=[];
 for(const record of captured?.records||[]){
  const matching=(visible.media_descriptors||[]).filter(d=>d.state==='loaded'&&d.ready_state>=2&&d.paused===true&&d.media_source&&record.aliases.includes(d.current_src));
  if(!matching.length)continue;
  try{validate(record);}catch(error){diagnostics.push({url:record.url,reason:error.message,observed_reasons:record.reasons});continue;}
  records.push(record);
  for(const d of matching)targets.push({path:d.position_path,url:d.current_src,identity:d.identity,src_attribute:d.src_attribute,source_attributes:d.source_attributes,current_time:d.current_time,video_width:d.video_width,video_height:d.video_height});
 }
 const bundle={version:VERSION,scope:'browser_derived_window_mse',records,targets,diagnostics,total_bytes:records.reduce((n,r)=>n+validate(r),0)};
 verifyBundle(bundle);return bundle;
}
function verifyBundle(bundle,origin=null){
 if(!bundle||bundle.version!==VERSION||bundle.scope!=='browser_derived_window_mse'||!Array.isArray(bundle.records)||bundle.records.length>32||!Array.isArray(bundle.targets)||bundle.targets.length>1000)throw Error('Invalid MSE reference bundle');
 let total=0;const aliases=new Set(),paths=new Set();
 for(const record of bundle.records){
  total+=validate(record);
  if(!Array.isArray(record.aliases)||!record.aliases.length||record.aliases.length>32||!record.aliases.includes(record.url))throw Error('Invalid MSE source association');
  for(const url of record.aliases){
   if(typeof url!=='string'||url.length>4096||!url.startsWith('blob:')||aliases.has(url)||(origin&&new URL(url).origin!==new URL(origin).origin))throw Error('Ambiguous or foreign MSE source');aliases.add(url);
  }
 }
 for(const t of bundle.targets){
  if(!t||typeof t.path!=='string'||!/^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9][0-9]*\))+$/.test(t.path)||paths.has(t.path)||!aliases.has(t.url)||!Number.isFinite(t.current_time)||t.current_time<0||!(t.src_attribute===null||typeof t.src_attribute==='string')||!Array.isArray(t.source_attributes)||!t.source_attributes.every(s=>typeof s==='string')||!t.identity||!['VIDEO','AUDIO'].includes(t.identity.kind)||!['none','metadata','auto',''].includes(t.identity.preload)||typeof t.identity.poster!=='string'||!Array.isArray(t.identity.sources)||!t.identity.sources.every(url=>typeof url==='string')||![t.video_width,t.video_height].every(n=>Number.isSafeInteger(n)&&n>=0))throw Error('Invalid MSE element association');paths.add(t.path);
 }
 if(total>MAX_BYTES||total!==bundle.total_bytes)throw Error('MSE reference aggregate limit or size mismatch');
 return total;
}
async function restoreReference(page,bundle,origin){
 if(!bundle)return {version:VERSION,eligible:0,results:[],live_resources:false};
 verifyBundle(bundle,origin);const results=[],deadline=Date.now()+15000;
 for(const t of bundle.targets){
  const matches=await page.evaluate(t=>{
   const e=document.querySelector(t.path);if(!e)return false;
   const sources=[...new Set([e.getAttribute('src'),...[...e.querySelectorAll('source[src]')].map(s=>s.getAttribute('src'))].filter(Boolean).map(url=>{try{const u=new URL(url,location.href);return ['http:','https:'].includes(u.protocol)?u.href:null;}catch{return null;}}).filter(Boolean))].sort();
   return e.tagName===t.identity.kind&&e.preload===t.identity.preload&&(e.poster||'')===t.identity.poster&&e.getAttribute('src')===t.src_attribute&&JSON.stringify([...e.querySelectorAll('source[src]')].map(s=>s.getAttribute('src')))===JSON.stringify(t.source_attributes)&&sources.length===t.identity.sources.length&&sources.every((url,i)=>url===t.identity.sources[i]);
  },t);
  if(!matches){results.push({path:t.path,status:'unmatched_reference'});continue;}
  const record=bundle.records.find(r=>r.aliases.includes(t.url)),budgetMs=Math.max(1,deadline-Date.now());
  const result=await restore(page,t.path,record,t.current_time,{budgetMs});
  if(result.status==='restored'&&(result.video_width!==t.video_width||result.video_height!==t.video_height))result.status='failed',result.reason='Observed MSE frame dimensions changed';
  results.push({path:t.path,...result});
 }
 return {version:VERSION,restoration_version:'frozen-observed-mse-restoration-v2',eligible:bundle.targets.length,results,live_resources:false,budget_ms:15000,scope:'decoded_observed_frame_not_application_tasks'};
}
Object.assign(module.exports,{reference,verifyBundle,restoreReference});
