'use strict';
const crypto=require('node:crypto');
const VERSION='frozen-media-ranges-v6';
function transportUrl(value){const u=new URL(value);if(['http:','https:'].includes(u.protocol))u.hash='';return u.href;}
const isHls=m=>/^(application|audio)\/(vnd\.apple\.mpegurl|x-mpegurl|mpegurl)(?:\s*;|$)/i.test(m||'');
const isMedia=m=>/^(video|audio)\//i.test(m||'');
function fragment(asset){
 const match=/^bytes (\d+)-(\d+)\/(\d+)$/.exec(asset.headers?.['content-range']||'');
 if(asset.http_status!==206||!match)throw Error('Frozen partial media lacks its original range');
 const [start,end,total]=match.slice(1).map(Number);
 if(![start,end,total].every(Number.isSafeInteger)||start>end||end>=total||end-start+1!==asset.body.length)throw Error('Invalid frozen partial media range');
 return {start,end,total,body:asset.body};
}
function assemble(records){
 const full=records.filter(a=>a.http_status!==206),parts=records.filter(a=>a.http_status===206).map(fragment);
 if(full.length){
  const chosen=full[full.length-1];
  if(full.some(a=>!a.body.equals(chosen.body))||parts.some(p=>p.total!==chosen.body.length||!p.body.equals(chosen.body.subarray(p.start,p.end+1))))throw Error('Conflicting frozen media bytes');
  return chosen;
 }
 parts.sort((a,b)=>a.start-b.start);const segments=[];
 for(const part of parts){
  if(part.total!==parts[0].total)throw Error('Conflicting frozen media lengths');
  const prev=segments.at(-1);
  if(!prev||part.start>prev.end+1){segments.push({...part});continue;}
  const overlap=Math.min(prev.end,part.end)-part.start+1;
  if(overlap>0&&!prev.body.subarray(part.start-prev.start,part.start-prev.start+overlap).equals(part.body.subarray(0,overlap)))throw Error('Conflicting frozen media overlap');
  if(part.end>prev.end){prev.body=Buffer.concat([prev.body,part.body.subarray(Math.max(0,overlap))]);prev.end=part.end;}
 }
 return {...records.at(-1),fragments:segments,total:parts[0]?.total};
}
function response(asset,range){
 if(asset.body_representation?.kind==='unsupported_encoded_range')throw Error('Encoded partial response cannot supply logical byte offsets');
 if(asset.http_status===206&&!asset.fragments)asset=assemble([asset]);
 if(asset.fragments){
  const headers={...asset.headers,'content-type':asset.mime,'accept-ranges':'bytes'};delete headers['content-range'];delete headers['content-length'];
  const invalid=()=>({status:416,headers:{...headers,'content-range':'bytes */'+asset.total},body:Buffer.alloc(0)});
  let start,end;
  if(!range){start=asset.fragments[0].start;end=asset.fragments[0].end;}
  else{const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||(!m[1]&&!m[2]))return invalid();start=m[1]?Number(m[1]):Math.max(0,asset.total-Number(m[2]));end=m[1]?(m[2]?Number(m[2]):asset.total-1):asset.total-1;}
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=asset.total)return invalid();
  const part=asset.fragments.find(p=>p.start<=start&&p.end>=start);if(!part)return invalid();end=Math.min(end,part.end,asset.total-1);
  const body=part.body.subarray(start-part.start,end-part.start+1);
  return {status:206,headers:{...headers,'content-range':`bytes ${start}-${end}/${asset.total}`,'content-length':String(body.length)},body};
 }
 const body=asset.body,headers={...asset.headers,'content-type':asset.mime};delete headers['content-range'];delete headers['content-length'];
 if(!range||!isMedia(asset.mime))return {status:200,headers:{...headers,'content-length':String(body.length)},body};
 const m=/^bytes=(\d*)-(\d*)$/.exec(range);
 if(!m||(!m[1]&&!m[2]))return {status:416,headers:{...headers,'content-range':'bytes */'+body.length},body:Buffer.alloc(0)};
 let start=m[1]?Number(m[1]):Math.max(0,body.length-Number(m[2]));
 let end=m[1]?(m[2]?Number(m[2]):body.length-1):body.length-1;
 end=Math.min(end,body.length-1);
 if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=body.length)return {status:416,headers:{...headers,'content-range':'bytes */'+body.length},body:Buffer.alloc(0)};
 const part=body.subarray(start,end+1);return {status:206,headers:{...headers,'accept-ranges':'bytes','content-range':`bytes ${start}-${end}/${body.length}`,'content-length':String(part.length)},body:part};
}
async function complete(assets,errors,fetch,validate,attempted=new Set(),observed=[],reserve,selectedOnly=false){
 const partial=new Map();for(const a of assets)if(!selectedOnly&&isMedia(a.mime)&&a.http_status===206)partial.set(transportUrl(a.url),a);
 for(const a of observed)if(isMedia(a.mime)&&!partial.has(transportUrl(a.url)))partial.set(transportUrl(a.url),a);
 let total=assets.reduce((n,a)=>n+Buffer.from(a.body,'base64').length,0);
 for(const [url,a]of partial){
  if(assets.some(v=>v.http_status===200&&(transportUrl(v.url)===url||v.redirect_chain?.some(r=>transportUrl(r.from)===url))))continue;
  if(attempted.has(url))continue;attempted.add(url);
  try{
   let current=url,result;const chain=[];
   for(let hop=0;hop<6;hop++){
    await validate(current);result=await fetch(current,require('./evidence_limits').resourceLimit(a.mime));
    if(result.status>=300&&result.status<400&&result.headers.location){const next=new URL(result.headers.location,current).href;chain.push({from:current,to:next,status:result.status,headers:Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'].includes(key)))});current=next;continue;}
    break;
   }
   const actualMime=result.headers['content-type']||a.mime;
   if(a.observed_kind&&!new RegExp('^'+a.observed_kind.toLowerCase()+'/','i').test(actualMime)&&!isHls(actualMime))throw Error('Observed loaded media did not return matching media MIME');
   const limit=require('./evidence_limits').resourceLimit(actualMime),body=result.body;
   const match=/^bytes 0-(\d+)\/(\d+)$/.exec(result.headers['content-range']||'');
   if(!body.length||body.length>limit||total+body.length>require('./evidence_limits').TOTAL_RESOURCE_BYTES)throw Error('media capture budget');
   if(isHls(actualMime)){
    if(!body.toString('utf8').startsWith('#EXTM3U\n')&&!body.toString('utf8').startsWith('#EXTM3U\r\n'))throw Error('Observed HLS media lacks a valid playlist signature');
    if(result.status!==200&&!(result.status===206&&match&&Number(match[1])+1===body.length&&Number(match[2])===body.length))throw Error('Observed HLS playlist is incomplete');
   }
   if(result.status===206&&!(match&&Number(match[1])+1===body.length&&Number(match[2])===body.length)){
    fragment({http_status:206,headers:result.headers,body});if(reserve)reserve(body.length);total+=body.length;
    const headers={...a.headers,...Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy','content-range','accept-ranges'].includes(key)))};
    assets.push({...a,url:current,redirect_chain:[...(a.redirect_chain||[]),...chain],mime:actualMime,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex'),headers,http_status:206,
     media_capture:{version:VERSION,requested_url:a.url,final_url:current,complete:false,bounded_fragment:true,bytes:body.length}});
    errors.push({url,reason:'Bounded recorded fragment; full playback is not captured',kind:'incomplete_media'});continue;
   }
   if(result.status!==200&&!(result.status===206&&match))throw Error('media response remains partial');
   if(reserve)reserve(body.length);
   total+=body.length;const headers={...a.headers,...Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy','accept-ranges'].includes(key)))};delete headers['content-range'];delete headers['content-length'];
   assets.push({...a,url:current,redirect_chain:[...(a.redirect_chain||[]),...chain],mime:actualMime,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex'),headers,http_status:200,
    media_capture:{version:VERSION,requested_url:a.url,final_url:current,complete:true,bytes:body.length,partial_hashes:assets.filter(v=>v.url===url).map(v=>v.sha256)}});
  }catch(e){errors.push({url,reason:e.message,kind:'incomplete_media'});}
 }
 return {assets,errors,bytes:total};
}
async function settle(page){
 await page.waitForFunction(()=>[...document.querySelectorAll('video,audio')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&getComputedStyle(e).display!=='none';}).every(e=>e.readyState>=2||e.error),{},{timeout:3000}).catch(()=>{});
 return page.evaluate(()=>[...document.querySelectorAll('video,audio')].map(e=>{e.pause();return {kind:e.tagName,src:e.currentSrc||e.src,ready_state:e.readyState,error:e.error?.code||null,current_time:e.currentTime};}));
}
module.exports={VERSION,transportUrl,isMedia,fragment,assemble,response,complete,settle};
