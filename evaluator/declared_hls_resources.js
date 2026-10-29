'use strict';
const crypto=require('node:crypto');
const limits=require('./evidence_limits');
const VERSION='declared-hls-resources-v6';
const budgets=new WeakMap();
function playlist(asset){if(!/mpegurl/i.test(asset.mime||'')&&!/\.m3u8(?:\?|$)/i.test(asset.url||''))return false;return Buffer.from(asset.body,'base64').toString('utf8').startsWith('#EXTM3U');}
function entries(text,base,windowSeconds=30){
 const lines=text.split(/\r?\n/).map(s=>s.trim()),out=[];let variants=false,segments=0,duration=0,nextDuration=0;
 if(lines.some(s=>/^#EXT-X-(KEY|SESSION-KEY):/.test(s)&&!s.includes('METHOD=NONE')))throw Error('Encrypted playlist requires additional evidence');
 if(lines.some(s=>s.startsWith('#EXT-X-BYTERANGE:')||s.startsWith('#EXT-X-MAP:')&&s.includes('BYTERANGE=')))throw Error('Playlist byte ranges require additional evidence');
 const add=(value,kind)=>{const url=new URL(value,base);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw Error('Invalid declared HLS URL');if(!out.some(ref=>ref.url===url.href))out.push({url:url.href,kind});};
 for(const line of lines){
  if(line.startsWith('#EXTINF:')){nextDuration=Number.parseFloat(line.slice(8));if(!Number.isFinite(nextDuration)||nextDuration<=0)throw Error('Invalid HLS segment duration');continue;}
  if(line.startsWith('#EXT-X-STREAM-INF:')){variants=true;continue;}
  if(/^#EXT-X-(MEDIA|MAP):/.test(line)){const uri=/URI="([^"]+)"/.exec(line);if(uri)add(uri[1],line.startsWith('#EXT-X-MAP:')?'media':'playlist');continue;}
  if(!line||line.startsWith('#'))continue;
  if(variants){add(line,'playlist');variants=false;}else{if(segments<8&&duration<windowSeconds)add(line,'media');segments++;duration+=nextDuration||30;nextDuration=0;}
 }
 return out;
}
function references(text,base){return entries(text,base).map(ref=>ref.url);}
async function complete(assets,errors,fetch,validate,attempted=new Set(),reserve,{observedMedia=[],allowOptional=true}={}){
 let total=assets.reduce((n,a)=>n+Buffer.from(a.body,'base64').length,0);
 if(!assets.some(playlist))return {assets,errors,bytes:total};
 if(!budgets.has(attempted))budgets.set(attempted,{requests:0,spentMs:0});
 const native=a=>Number.isSafeInteger(a.native_response_sequence)&&a.native_response_sequence>0&&['browser_response_entity','decoded_complete_entity'].includes(a.body_representation?.kind);
 const selected=new Map();for(const a of assets.filter(playlist)){const prev=selected.get(a.url);if(!prev||(!native(prev)&&!native(a))||(native(a)&&(!native(prev)||a.native_response_sequence>prev.native_response_sequence)))selected.set(a.url,a);}
 const times=observedMedia.map(r=>r.current_time).filter(v=>Number.isFinite(v)&&v>=0);
 const frameWindow=times.length?Math.min(30,Math.max(...times)+2):30;
 const budget=budgets.get(attempted),started=Date.now();budget.deadline=started+Math.max(0,45000-budget.spentMs);
 const receipt=()=>({version:'active-hls-recovery-budget-v1',requests:budget.requests,elapsed_ms:budget.spentMs+Math.max(0,Date.now()-started),remaining_ms:Math.max(0,budget.deadline-Date.now()),limit_ms:45000,request_limit:40});
 try{
 const queue=[...selected.values()],seenPlaylists=new Set(),mediaLanes=[];let pendingDiscovery=false;
 const limited=()=>budget.requests>=40||Date.now()>=budget.deadline||total>=limits.TOTAL_RESOURCE_BYTES;
 const existing=requested=>assets.find(a=>a.url===requested||a.redirect_chain?.some(r=>r.from===requested));
 const capture=async requested=>{
   const recorded=existing(requested);if(recorded)return recorded;
   if(attempted.has(requested))return null;
   if(limited())return null;
   attempted.add(requested);
   try{
    let current=requested,result;const chain=[];
    for(let hop=0;hop<6;hop++){
     if(budget.requests>=40||Date.now()>=budget.deadline)throw Error('Declared HLS request or time budget');
     await validate(current);budget.requests++;result=await fetch(current,8000000);
     if(result.status>=300&&result.status<400&&result.headers.location){const next=new URL(result.headers.location,current).href;chain.push({from:current,to:next,status:result.status,headers:Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'].includes(key)))});current=next;continue;}break;
    }
    const body=result.body,mime=result.headers['content-type']||'',isPlaylist=body.subarray(0,7).toString()==='#EXTM3U';
    if(result.status!==200||!body.length||(!isPlaylist&&!/^(video|audio)\/|^application\/(octet-stream|mp2t)/i.test(mime)))throw Error('Declared HLS resource has an unsupported response');
    if(body.length>limits.resourceLimit(mime)||total+body.length>limits.TOTAL_RESOURCE_BYTES)throw Error('Declared HLS capture budget');
    if(reserve)reserve(body.length);
    total+=body.length;
    const asset={url:current,mime,http_status:200,body:body.toString('base64'),sha256:crypto.createHash('sha256').update(body).digest('hex'),redirect_chain:chain,
     headers:Object.fromEntries(Object.entries(result.headers).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'].includes(key))),
     declared_capture:{version:VERSION,requested_url:requested,final_url:current,bytes:body.length}};
    assets.push(asset);return asset;
   }catch(e){errors.push({url:requested,kind:'declared_hls_unavailable',reason:e.message});return null;}
 };
 // Before optional rendition discovery, recover the bounded frame window
 // of playlists actually fetched by the native browser. Native bytes already
 // recorded are reused, and the same shared request/time/byte limits apply.
 const nativeLanes=[];
 for(const parent of queue.filter(native)){
  try{const refs=entries(Buffer.from(parent.body,'base64').toString('utf8'),parent.url,frameWindow);
   const lane=refs.filter(ref=>ref.kind==='media').map(ref=>ref.url);if(lane.length)nativeLanes.push(lane);
  }catch(e){errors.push({url:parent.url,kind:'declared_hls_unavailable',reason:e.message});}
 }
 let nativePending=true;
 while(nativePending&&!limited()){
  nativePending=false;
  for(const lane of nativeLanes){
   while(lane.length&&(existing(lane[0])||attempted.has(lane[0])))lane.shift();
   if(!lane.length)continue;nativePending=true;await capture(lane.shift());if(limited())break;
  }
 }
 if(!allowOptional){if(limited()&&nativeLanes.some(lane=>lane.length))errors.push({kind:'declared_hls_limit',reason:'Native HLS frame window reached shared limits'});return {assets,errors,bytes:total,hls_recovery_budget:receipt()};}
 // Discover the declared renditions first, then give each rendition one
 // resource per round. A long first rendition must not consume all forty
 // requests before another player's first segment has been captured.
 for(let i=0;i<queue.length;i++){
  const parent=queue[i];if(seenPlaylists.has(parent.url))continue;seenPlaylists.add(parent.url);
  let refs;try{refs=entries(Buffer.from(parent.body,'base64').toString('utf8'),parent.url,native(parent)?frameWindow:30);}catch(e){errors.push({url:parent.url,kind:'declared_hls_unavailable',reason:e.message});continue;}
  mediaLanes.push(refs.filter(ref=>ref.kind==='media').map(ref=>ref.url));
  for(const ref of refs.filter(ref=>ref.kind==='playlist')){
   const child=await capture(ref.url);if(child&&playlist(child))queue.push(child);
   if(limited()){pendingDiscovery ||= refs.some(ref=>ref.kind==='playlist'&&!existing(ref.url)&&!attempted.has(ref.url));break;}
  }
 }
 let pending=true;
 while(pending&&!limited()){
  pending=false;
  for(const lane of mediaLanes){
   while(lane.length&&(existing(lane[0])||attempted.has(lane[0])))lane.shift();
   if(!lane.length)continue;pending=true;
   await capture(lane.shift());if(limited())break;
  }
 }
 if(limited()&&(pendingDiscovery||nativeLanes.some(lane=>lane.length)||mediaLanes.some(lane=>lane.some(url=>!existing(url)&&!attempted.has(url)))))errors.push({kind:'declared_hls_limit',reason:'Declared HLS recovery reached its request, time or byte limit'});
 return {assets,errors,bytes:total,hls_recovery_budget:receipt()};
 }finally{budget.spentMs+=Math.max(0,Date.now()-started);}
}
module.exports={VERSION,references,complete};
