'use strict';
const crypto=require('node:crypto');
function collect(page){
 const cors=require('./frozen_cors').collect(page);
 const assets=[],errors=[],tasks=[];let bytes=0;const reserve=size=>{if(bytes+size>require('./evidence_limits').TOTAL_RESOURCE_BYTES)throw Error('resource capture budget');bytes+=size;};const imageRecovery={attempted:new Set(),elapsed_ms:0},attemptedMedia=new Set(),attemptedHls=new Set();
 let responseSequence=0;
 const listener=response=>{
  const native_response_sequence=++responseSequence;
  // Responses whose bodies are never retained must not consume a body slot.
  // Keep their ordinal: temporal playlist selection still uses receipt order.
  const request=response.request();if(request.method()!=='GET'||response.status()<200||response.status()>=300)return;
  if(tasks.length>=1000){errors.push({url:response.url(),reason:'resource response count limit'});return;}
  tasks.push((async()=>{
   let timer;
   try{
    const mime=response.headers()['content-type']||'application/octet-stream';
    const limit=require('./evidence_limits').resourceLimit(mime);
    if(Number(response.headers()['content-length']||0)>limit)throw Error('resource size limit');
    const body=await Promise.race([response.body(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('resource body timeout')),15000);})]);
    if(body.length>limit)throw Error('resource capture budget');
    const representation=require('./browser_response_body').observed(response.status(),response.headers(),body);
    if(representation.body_representation.kind==='unsupported_encoded_range')errors.push({url:response.url(),kind:'encoded_range_unavailable',reason:representation.body_representation.reason});
    reserve(body.length);assets.push({url:response.url(),mime,...representation,native_response_sequence,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex'),
     redirect_chain:await require('./frozen_redirects').capture(request),
     headers:representation.headers});
   }catch(error){errors.push({url:response.url(),reason:error.message});}finally{clearTimeout(timer);}
  })());
 };
 page.on('response',listener);
 return {ready:cors.ready,reservedBytes:()=>bytes,reserveDerived(size){if(!Number.isSafeInteger(size)||size<0)throw Error('Invalid derived resource size');reserve(size);},async finish({close=true}={}){if(close)page.off('response',listener);await Promise.allSettled(tasks);const preflights=await cors.finish(close);const fetch=async(url,limit,range=true)=>{
 const response=await page.context().request.get(url,{...(range?{headers:{Range:'bytes=0-'+(limit-1)}}:{}),maxRedirects:0,timeout:15000});
 try{const headers=response.headers();if(Number(headers['content-length']||0)>limit)throw Error('media size limit');return {status:response.status(),headers,body:await response.body()};}finally{await response.dispose();}
 };const validate=url=>require('./harness_evidence').publicUrl(url);
 const selectedMedia=typeof page.evaluate==='function'?await page.evaluate(()=>Array.from(document.querySelectorAll('video,audio')).filter(e=>e.readyState>=2&&/^https?:/.test(e.currentSrc)).map(e=>({url:e.currentSrc,mime:e.tagName.toLowerCase()+'/unknown',observed_kind:e.tagName,current_time:e.currentTime}))):[];
 const media=await require('./frozen_media').complete(assets,errors,fetch,validate,attemptedMedia,selectedMedia.filter(a=>a&&a.observed_kind),reserve,true);
 const document=await page.content();
 // Capture the browser-selected responsive variants, including URLs without
 // file extensions. Configuration strings alone miss currentSrc in srcset.
 const visible=typeof page.evaluate==='function'?await require('./replay_admission').visibleImageUrls(page):[];
 const selected=close&&typeof page.evaluate==='function'?await page.evaluate(()=>Array.from(document.images,img=>img.currentSrc||img.src).filter(Boolean)):[];
 const imageUrls=require('./declared_image_resources').urls;
 const candidates=[...new Set([...imageUrls(visible,page.url()),...imageUrls(selected,page.url()),...(close?imageUrls(document,page.url()):[])])];
 const images=await require('./declared_image_resources').complete(candidates,page.url(),media.assets,media.errors,(url,limit)=>fetch(url,limit,false),validate,reserve,imageRecovery);
 const hls=await require('./declared_hls_resources').complete(images.assets,images.errors,(url,limit)=>fetch(url,limit,false),validate,attemptedHls,reserve,{observedMedia:selectedMedia,allowOptional:close});
 return {version:'native-resource-package-v4',...hls,...preflights,body_representation_version:require('./browser_response_body').VERSION,native_response_order_version:'browser-response-sequence-v1',native_response_capture_scope_version:'successful-get-body-budget-v1',resource_recovery_phase_version:'native-before-optional-resources-v1',image_recovery_priority_version:'reachable-content-current-src-v1',image_recovery_version:require('./declared_image_resources').VERSION,media_recovery_version:require('./frozen_media').VERSION,media_recovery_scope:'native_loaded_current_src',resource_budget_version:'shared-native-resource-budget-v1',bytes:assets.reduce((n,a)=>n+Buffer.from(a.body,'base64').length,0)};}};
}
module.exports={collect};
