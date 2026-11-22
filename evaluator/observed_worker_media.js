'use strict';
const crypto=require('node:crypto'),init=require('./media_init_segment');
const VERSION='observed-worker-media-metadata-v2',MAX_BYTES=8000000;
const pages=new WeakMap();
function observe(){
 const key=Symbol.for('a11yharness.workerMedia'),sources=new WeakMap(),buffers=new WeakMap(),handles=new WeakMap(),records=[];let saved=0,overflow=false;
 if(self[key])return;
 const record=s=>{let r=sources.get(s);if(!r){if(records.length>=8){overflow=true;return null;}r={source:s,getter:false,transfer:false,unsupported:false,buffers:[]};sources.set(s,r);records.push(r);}return r;};
 if(typeof MediaSource==='undefined'||typeof SourceBuffer==='undefined')return;
 const d=Object.getOwnPropertyDescriptor(MediaSource.prototype,'handle');
 if(!d?.get||!d.configurable)return;
 Object.defineProperty(MediaSource.prototype,'handle',{...d,get(){const h=Reflect.apply(d.get,this,[]),r=record(this);if(r){r.getter=true;handles.set(h,r);}return h;}});
 const post=self.postMessage;self.postMessage=function(...args){const list=Array.isArray(args[1])?args[1]:args[1]?.transfer||[],rs=list.map(h=>handles.get(h)).filter(Boolean);const result=Reflect.apply(post,this,args);rs.forEach(r=>r.transfer=true);return result;};
 const add=MediaSource.prototype.addSourceBuffer;MediaSource.prototype.addSourceBuffer=function(...args){const b=Reflect.apply(add,this,args),r=record(this);if(r){if(r.buffers.length>=8)r.unsupported=true;else{const e={owner:r,buffer:b,codec:typeof args[0]==='string'?args[0]:null,first:null,resets:new Set()};r.buffers.push(e);buffers.set(b,e);}}return b;};
 const append=SourceBuffer.prototype.appendBuffer;SourceBuffer.prototype.appendBuffer=function(...args){const e=buffers.get(this);let first;if(e&&!e.first){const v=args[0],raw=ArrayBuffer.isView(v)?new Uint8Array(v.buffer,v.byteOffset,v.byteLength):v instanceof ArrayBuffer?new Uint8Array(v):null;if(raw){const n=Math.min(raw.length,500000-saved);if(n>0)first={bytes:raw.slice(0,n),source_byte_length:raw.length,mode:this.mode,timestamp_offset:this.timestampOffset};else e.owner.unsupported=true;}}const result=Reflect.apply(append,this,args);if(first){e.first=first;saved+=first.bytes.length;}return result;};
 for(const name of ['remove','abort','changeType']){const original=SourceBuffer.prototype[name];if(original)SourceBuffer.prototype[name]=function(...args){const result=Reflect.apply(original,this,args);const e=buffers.get(this);if(e){if(name==='changeType')e.owner.unsupported=true;else e.resets.add(name);}return result;};}
 const remove=MediaSource.prototype.removeSourceBuffer;MediaSource.prototype.removeSourceBuffer=function(...args){const result=Reflect.apply(remove,this,args);const r=sources.get(this);if(r)r.unsupported=true;return result;};
 self[key]=()=>({overflow,records:records.map(r=>({getter:r.getter,transfer:r.transfer,unsupported:r.unsupported,ready_state:r.source.readyState,native_buffer_count:r.source.sourceBuffers.length,buffers:r.buffers.map(e=>({codec:e.codec,updating:e.buffer.updating,reset_operations:[...e.resets],final_buffered_count:e.buffer.buffered.length,final_mode:e.buffer.mode,final_timestamp_offset:e.buffer.timestampOffset,first:e.first?{...e.first,bytes:[...e.first.bytes]}:null}))}))});
}
async function install(page){
 const workers=[];pages.set(page,workers);page.on('worker',worker=>{if(workers.length>=16)return;const e={worker,url:worker.url(),index:workers.length};workers.push(e);e.installed=worker.evaluate(observe).catch(()=>null);});
}
function metadata(m){return m?.src_object_kind==='MediaSourceHandle'&&m.ready_state===1&&m.paused===true&&m.current_time===0&&m.error===null&&Array.isArray(m.buffered_ranges)&&m.buffered_ranges.length===0&&Number.isInteger(m.video_width)&&m.video_width>0&&Number.isInteger(m.video_height)&&m.video_height>0;}
async function reference(page,visible){
 const targets=(visible.media_descriptors||[]).filter(m=>m.src_object_kind==='MediaSourceHandle'),sources=[];
 for(const e of pages.get(page)||[]){await e.installed;let s;try{s=await e.worker.evaluate(()=>self[Symbol.for('a11yharness.workerMedia')]?.()||null);}catch{continue;}
  for(const r of s?.records||[])if(r.getter&&r.transfer)sources.push({worker:e.index,url:e.url,overflow:s.overflow,...r});
 }
 const result={version:VERSION,observation_scope:'passive-worker-arrival-no-before-author-guarantee',records:[],total_bytes:0,unsupported:targets.length,diagnostics:{visible_handle_count:targets.length,observed_transferred_source_count:sources.length,sources:sources.map(s=>({worker_index:s.worker,unsupported_mutation:s.unsupported,overflow:s.overflow,native_buffer_count:s.native_buffer_count,buffers:s.buffers.map(b=>({codec:b.codec,updating:b.updating,reset_operations:b.reset_operations,final_buffered_count:b.final_buffered_count,final_mode:b.final_mode,final_timestamp_offset:b.final_timestamp_offset,first_append_observed:!!b.first}))}))}};
 if(targets.length!==1||sources.length!==1||!metadata(targets[0]))return result;
 const s=sources[0];if(s.overflow||s.unsupported||!s.buffers.length||s.buffers.length>8||s.native_buffer_count!==s.buffers.length||s.buffers.some(b=>b.updating||!b.first||b.final_buffered_count!==0||b.final_mode!==b.first.mode||b.final_timestamp_offset!==b.first.timestamp_offset))return result;
 try{const buffers=s.buffers.map(b=>{if(typeof b.codec!=='string'||b.codec.length>256||!['segments','sequence'].includes(b.first.mode)||b.first.timestamp_offset!==0)throw Error('Unsupported worker buffer settings');const p=init.extract(Buffer.from(b.first.bytes),/mp4/i.test(b.codec)?'video/mp4':/webm/i.test(b.codec)?'video/webm':'unsupported');return{codec:b.codec,reset_operations:b.reset_operations,final_buffered_count:0,container:p.container,mode:b.first.mode,timestamp_offset:0,source_byte_length:b.first.source_byte_length,byte_length:p.byte_length,sha256:p.sha256,body:p.body.toString('base64')};});
  result.total_bytes=buffers.reduce((n,b)=>n+b.byte_length,0);result.records=[{worker_index:s.worker,worker_url:s.url,handle_getter_observed:true,handle_transfer_observed:true,native_buffer_count:s.native_buffer_count,target:targets[0],buffers}];result.unsupported=0;
 }catch(error){result.diagnostics.rejection=String(error);result.records=[];result.total_bytes=0;}
 return result;
}
function verifyBundle(bundle){
 if(!bundle)return 0;
 if(bundle.version!==VERSION||bundle.observation_scope!=='passive-worker-arrival-no-before-author-guarantee'||!Array.isArray(bundle.records)||bundle.records.length>1)throw Error('Invalid worker media reference');
 let total=0;for(const r of bundle.records){if(!r.handle_getter_observed||!r.handle_transfer_observed||!metadata(r.target)||typeof r.target.position_path!=='string'||!/^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9][0-9]*\))+$/.test(r.target.position_path)||!r.target.identity||![0,1,2,3].includes(r.target.network_state)||!Array.isArray(r.buffers)||!r.buffers.length||r.buffers.length>8)throw Error('Invalid worker media association');
  for(const b of r.buffers){if(!Array.isArray(b.reset_operations)||b.reset_operations.length>2||b.reset_operations.some(x=>!['remove','abort'].includes(x))||b.final_buffered_count!==0)throw Error('Invalid worker metadata reset evidence');if(typeof b.codec!=='string'||b.codec.length>256||!['segments','sequence'].includes(b.mode)||b.timestamp_offset!==0||typeof b.body!=='string'||!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(b.body))throw Error('Invalid worker init settings');const raw=Buffer.from(b.body,'base64');if(raw.length!==b.byte_length||crypto.createHash('sha256').update(raw).digest('hex')!==b.sha256||!Number.isInteger(b.source_byte_length)||b.source_byte_length<raw.length)throw Error('Invalid worker init checksum');const p=init.extract(raw,b.container);if(p.byte_length!==raw.length)throw Error('Worker init contains frames');total+=raw.length;if(total>MAX_BYTES)throw Error('Worker init byte limit exceeded');}
 }if(total!==bundle.total_bytes)throw Error('Worker init accounting mismatch');return total;
}
// Uses native decoder objects and preserves author CSP. A denied blob worker is a failure.
async function restoreReference(page,bundle){
 if(!bundle)return{version:VERSION,restored:0};verifyBundle(bundle);
 if(bundle.unsupported)throw Error('Unsupported acquired worker media');
 if(!bundle.records.length)return{version:VERSION,restored:0};
 const script=`const source=new MediaSource();const handle=source.handle;postMessage({handle},[handle]);source.addEventListener('sourceopen',()=>{postMessage({open:true});onmessage=async e=>{try{const buffers=e.data.map(b=>{const buffer=source.addSourceBuffer(b.codec);buffer.mode=b.mode;return buffer;});for(let i=0;i<buffers.length;i++){await new Promise((resolve,reject)=>{const b=buffers[i];b.onupdateend=resolve;b.onerror=()=>reject(Error('Decoder error'));b.appendBuffer(Uint8Array.from(e.data[i].bytes));});}postMessage({done:true});}catch(e){postMessage({error:String(e)});}};});`;
 const before=await page.content();const results=await page.evaluate(async({records,script})=>{
  const identity=e=>({kind:e.tagName,preload:e.preload,poster:e.poster||'',sources:[e.getAttribute('src'),...[...e.querySelectorAll('source[src]')].map(s=>s.getAttribute('src'))].filter(Boolean).map(s=>{try{return new URL(s,document.baseURI).href;}catch{return s;}}).filter(s=>/^https?:/.test(s))});
  const same=(a,b)=>a.kind===b.kind&&a.preload===b.preload&&a.poster===b.poster&&JSON.stringify([...new Set(a.sources)].sort())===JSON.stringify(b.sources);
  const out=[];for(const r of records){const e=document.querySelector(r.target.position_path);if(!e||!same(identity(e),r.target.identity)||e.getAttribute('src')!==r.target.src_attribute||JSON.stringify([...e.querySelectorAll('source[src]')].map(s=>s.getAttribute('src')))!==JSON.stringify(r.target.source_attributes))throw Error('Worker target identity changed');
   const url=URL.createObjectURL(new Blob([script],{type:'application/javascript'}));let worker;try{worker=new Worker(url);(window[Symbol.for('a11yharness.restoredMediaWorkers')]||= []).push(worker);await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Worker metadata decoder deadline')),10000);const fail=x=>{clearTimeout(timer);reject(Error(String(x)));};worker.onerror=x=>fail(x.message);worker.onmessage=x=>{if(x.data.handle)e.srcObject=x.data.handle;if(x.data.open)worker.postMessage(r.buffers.map(b=>({codec:b.codec,mode:b.mode,bytes:[...Uint8Array.from(atob(b.body),c=>c.charCodeAt(0))]})));if(x.data.error)fail(x.data.error);if(x.data.done){clearTimeout(timer);resolve();}};});
    await new Promise(resolve=>setTimeout(resolve,100));const t=r.target;const state={ready_state:e.readyState,network_state:e.networkState,current_time:e.currentTime,paused:e.paused,error:e.error?.code||null,video_width:e.videoWidth,video_height:e.videoHeight,buffered:e.buffered.length,kind:e.srcObject?.constructor.name};if(state.ready_state!==t.ready_state||state.network_state!==t.network_state||state.current_time!==t.current_time||state.paused!==t.paused||state.error!==t.error||state.video_width!==t.video_width||state.video_height!==t.video_height||state.buffered!==0||state.kind!=='MediaSourceHandle')throw Error('Worker metadata state mismatch: '+JSON.stringify(state));out.push(state);
   }catch(error){worker?.terminate();throw error;}finally{URL.revokeObjectURL(url);}
  }return out;
 },{records:bundle.records,script});if(await page.content()!==before)throw Error('Worker restoration changed HTML');return{version:VERSION,restored:results.length,states:results};
}
module.exports={VERSION,MAX_BYTES,install,reference,verifyBundle,restoreReference,metadata};
