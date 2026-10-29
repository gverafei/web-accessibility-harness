'use strict';
const crypto=require('node:crypto');
const VERSION='declared-image-resources-v3';
// Capture only image URLs declared by the acquired document. This neither
// executes widgets nor follows links, APIs, forms or arbitrary script strings.
function urls(document,base){
 const found=new Set();
 if(Array.isArray(document)){
  for(const value of document){if(typeof value!=='string'||!value)continue;try{const url=new URL(value,base);if(['http:','https:'].includes(url.protocol)&&!url.username&&!url.password)found.add(url.href);}catch{}}
  return [...found];
 }
 for(const match of document.matchAll(/["']((?:https?:\/\/|\/)[^"'<>\s]+\.(?:png|jpe?g|webp|gif|svg|avif)(?:\?[^"'<>\s]*)?)["']/gi)){
  try{const url=new URL(match[1].replace(/&amp;/g,'&').replace(/\\\//g,'/'),base);if(['http:','https:'].includes(url.protocol)&&!url.username&&!url.password)found.add(url.href);}catch{}
 }
 return [...found];
}
async function complete(document,base,assets,errors,fetch,validate,reserve,state={attempted:new Set(),elapsed_ms:0}){
 let total=assets.reduce((n,a)=>n+Buffer.from(a.body,'base64').length,0);
 const missing=urls(document,base).filter(url=>!state.attempted.has(url)&&!assets.some(a=>a.url===url||a.declared_capture?.requested_url===url||a.redirect_chain?.some(r=>r.from===url)));
 const remaining=Math.max(0,200-state.attempted.size);
 if(missing.length>remaining)errors.push({kind:'declared_image_limit',reason:'More than 200 missing declared images; bounded recovery only'});
 const started=Date.now(),deadline=started+Math.max(0,60000-state.elapsed_ms);
 try{for(const requested of missing.slice(0,remaining)){
  if(Date.now()>=deadline||total>=require('./evidence_limits').TOTAL_RESOURCE_BYTES){errors.push({kind:'declared_image_limit',reason:'Declared image recovery reached its time or aggregate byte limit'});break;}
  state.attempted.add(requested);
  try{
   let current=requested,result;const chain=[];
   for(let hop=0;hop<6;hop++){
    await validate(current);result=await fetch(current,8000000);
    if(result.status>=300&&result.status<400&&result.headers.location){
     const next=new URL(result.headers.location,current).href;
     chain.push({from:current,to:next,status:result.status,headers:Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'].includes(key)))});current=next;continue;
    }
    break;
   }
   const mime=result.headers['content-type']||'';
   if(result.status!==200||!/^image\//i.test(mime))throw Error('Declared image did not return an image body');
   const body=result.body;
   if(!body.length||body.length>require('./evidence_limits').resourceLimit(mime)||total+body.length>require('./evidence_limits').TOTAL_RESOURCE_BYTES)throw Error('Declared image capture budget');
   if(reserve)reserve(body.length);
   total+=body.length;
   assets.push({url:current,mime,http_status:200,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex'),
    redirect_chain:chain,headers:Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'].includes(key))),
    declared_capture:{version:VERSION,requested_url:requested,final_url:current,bytes:body.length}});
  }catch(error){errors.push({url:requested,kind:'declared_image_unavailable',reason:error.message});}
 }}finally{state.elapsed_ms+=Date.now()-started;}
 return {assets,errors,bytes:total};
}
module.exports={VERSION,urls,complete};
