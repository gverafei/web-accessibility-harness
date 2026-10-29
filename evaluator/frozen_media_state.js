'use strict';
const VERSION='frozen-observed-media-restoration-v4';
async function restore(page,reference,assetUrls){
 if(!Array.isArray(reference)||reference.length>1000)throw Error('Invalid observed media reference');
 // Legacy references and MSE/blob players cannot establish an exact frame.
 const eligible=reference.filter(r=>r?.position_version==='observed-media-position-v1'&&r.state==='loaded'&&r.ready_state>=2&&r.paused===true&&!r.media_source&&Number.isFinite(r.current_time)&&r.current_time>=0&&typeof r.position_path==='string'&&/^html(?: > (?:[a-z][a-z0-9-]*):nth-of-type\([1-9][0-9]*\))+$/.test(r.position_path)&&r.identity&&['VIDEO','AUDIO'].includes(r.identity.kind)&&r.identity.sources?.includes(r.current_src)&&assetUrls.some(url=>require('./frozen_media').transportUrl(url)===require('./frozen_media').transportUrl(r.current_src)));
 if(new Set(eligible.map(r=>r.position_path)).size!==eligible.length)throw Error('Ambiguous observed media positions');
 return page.evaluate(async({eligible,version})=>{
  const identity=e=>({kind:e.tagName,preload:e.preload,poster:e.poster||'',sources:[...new Set([e.getAttribute('src'),...[...e.querySelectorAll('source[src]')].map(s=>s.getAttribute('src'))].filter(Boolean).map(url=>{try{return new URL(url,location.href).href;}catch{return null;}}).filter(Boolean))].sort()});
  const deadline=Date.now()+15000;
  const wait=async predicate=>{while(Date.now()<deadline&&!predicate())await new Promise(r=>setTimeout(r,50));return predicate();};
  const results=await Promise.all(eligible.map(async r=>{
   const e=document.querySelector(r.position_path);
   const observed=e&&identity(e);
   if(!observed||!['kind','preload','poster'].every(k=>observed[k]===r.identity[k])||observed.sources.length!==r.identity.sources.length||!observed.sources.every((url,index)=>url===r.identity.sources[index])){return {path:r.position_path,status:'unmatched_reference'};}
   const preload=e.getAttribute('preload');
   try{
    e.pause();
    if(e.readyState<2){e.preload='auto';e.load();}
    if(!await wait(()=>e.readyState>=2||e.error)||e.error)throw Error('Frozen media did not decode');
    if(Math.abs(e.currentTime-r.current_time)>0.01){e.currentTime=r.current_time;if(!await wait(()=>!e.seeking&&e.readyState>=2&&Math.abs(e.currentTime-r.current_time)<=0.01))throw Error('Observed media frame unavailable');}
    e.pause();return {path:r.position_path,status:'restored',time:e.currentTime,ready_state:e.readyState};
   }catch(error){return {path:r.position_path,status:'failed',reason:error.message,original_time:r.current_time,actual_time:e.currentTime,ready_state:e.readyState,network_state:e.networkState,media_error:e.error?.code||null,current_src:e.currentSrc,buffered:Array.from({length:e.buffered.length},(_,i)=>[e.buffered.start(i),e.buffered.end(i)])};}
   finally{if(preload===null)e.removeAttribute('preload');else e.setAttribute('preload',preload);}
  }));
  return {version,eligible:eligible.length,results,live_resources:false,frame_time_tolerance_seconds:0.01,budget_ms:15000};
 },{eligible,version:VERSION});
}
module.exports={VERSION,restore};
