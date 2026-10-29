'use strict';
// Preserve browser-observed read preflights; never manufacture CORS grants.
const VERSION='frozen-read-cors-v1';
const REPLAY_VERSION='frozen-read-cors-replay-v2';
function responseHeaders(headers){
 const reply=lower(headers);
 // CDP joins repeated header fields with LF. Vary is a token list, so
 // preserve all observed values as a comma list; never normalize grants.
 if(reply.vary?.includes('\n')&&!reply.vary.includes('\r')){
  const fields=reply.vary.split('\n');
  if(fields.every(v=>v.trim()&&v.split(',').every(t=>/^[-!#$%&'*+.^_`|~0-9a-z]+$/i.test(t.trim()))))reply.vary=fields.join(', ');
 }
 return reply;
}
const responseNames=new Set(['access-control-allow-origin','access-control-allow-credentials','access-control-allow-methods','access-control-allow-headers','access-control-max-age','vary']);
function lower(headers){return Object.fromEntries(Object.entries(headers||{}).map(([k,v])=>[k.toLowerCase(),String(v)]));}
function names(value){
 const entries=String(value||'').split(',').map(v=>v.trim().toLowerCase()).filter(Boolean);
 if(entries.some(v=>!/^[-!#$%&'*+.^_`|~0-9a-z]+$/.test(v)))throw Error('Invalid preflight header name');
 return [...new Set(entries)].sort().join(',');
}
function key(url,headers){
 const h=lower(headers);
 return JSON.stringify([new URL(url).href,h.origin,h['access-control-request-method'],names(h['access-control-request-headers'])]);
}
function index(records=[],origin){
 if(!Array.isArray(records)||records.length>1000)throw Error('Invalid frozen CORS records');
 const map=new Map(),ambiguous=new Set();
 for(const record of records){
  const url=new URL(record.url),h=lower(record.request_headers),reply=responseHeaders(record.headers);
  if(record.version!==VERSION||!['http:','https:'].includes(url.protocol)||url.username||url.password||h.origin!==new URL(origin).origin||h['access-control-request-method']!=='GET'||![200,204].includes(record.status))throw Error('Invalid frozen read preflight');
  if(Object.entries(reply).some(([k,v])=>!responseNames.has(k)||/[\r\n]/.test(v)))throw Error('Invalid frozen CORS response headers');
  const id=key(record.url,h),entry={status:record.status,headers:reply};
  if(map.has(id)&&JSON.stringify(map.get(id))!==JSON.stringify(entry)){ambiguous.add(id);map.delete(id);}
  else if(!ambiguous.has(id))map.set(id,entry);
 }
 return {lookup:(url,headers)=>map.get(key(url,headers)),size:map.size,ambiguous:[...ambiguous]};
}
function collect(page){
 const records=[],pending=new Map(),errors=[];let session;
 const ready=(async()=>{
  // Minimal page doubles do not expose CDP; actual native browsers always do.
  if(typeof page.context().newCDPSession!=='function')return;
  session=await page.context().newCDPSession(page);
  session.on('Network.requestWillBeSent',e=>{
   const h=lower(e.request.headers);
   if(e.request.method==='OPTIONS'&&h['access-control-request-method']==='GET'&&pending.size<1000)
    pending.set(e.requestId,{version:VERSION,url:e.request.url,request_headers:{origin:h.origin,'access-control-request-method':'GET','access-control-request-headers':names(h['access-control-request-headers'])}});
  });
  function response(id,status,headers){const r=pending.get(id);if(r){r.status=status;r.headers=Object.fromEntries(Object.entries(lower(headers)).filter(([k])=>responseNames.has(k)));}}
  session.on('Network.responseReceived',e=>response(e.requestId,e.response.status,e.response.headers));
  session.on('Network.responseReceivedExtraInfo',e=>response(e.requestId,e.statusCode,e.headers));
  session.on('Network.loadingFinished',e=>{const r=pending.get(e.requestId);if(r&&[200,204].includes(r.status)&&records.length<1000)records.push(r);pending.delete(e.requestId);});
  session.on('Network.loadingFailed',e=>{if(pending.has(e.requestId))errors.push({url:pending.get(e.requestId).url,reason:e.errorText,kind:'read_preflight_failed'});pending.delete(e.requestId);});
  await session.send('Network.enable');
 })();
 return {ready,async finish(close=true){await ready;if(close&&session){await session.detach();session=null;}return {preflights:records.slice(),preflight_errors:errors.slice(),preflight_policy:VERSION};}};
}
module.exports={VERSION,REPLAY_VERSION,key,index,collect};
