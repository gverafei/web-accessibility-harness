'use strict';
const VERSION='frozen-redirects-v4';
const SECURITY_HEADERS=['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'];
async function capture(request){
 const chain=[];let current=request,previous;
 while((previous=current.redirectedFrom())){
  if(chain.length>=16)throw new Error('Frozen redirect chain exceeds limit');
  const response=await previous.response();
  if(!response||previous.method()!=='GET')throw new Error('Unverifiable frozen resource redirect');
  chain.unshift({from:previous.url(),to:current.url(),status:response.status(),
   headers:Object.fromEntries(Object.entries(response.headers()).filter(([key])=>SECURITY_HEADERS.includes(key)))});
  current=previous;
 }
 return chain;
}
function index(assets){
 const redirects=new Map(),ambiguous=new Map();
 for(const asset of assets.values()){
  const extra=asset.additional_redirect_chains||[];
  if(!Array.isArray(extra)||extra.length>64)throw new Error('Invalid additional frozen redirect chains');
  for(const chain of [asset.redirect_chain||[],...extra]){
  if(!Array.isArray(chain)||chain.length>16)throw new Error('Invalid frozen redirect chain');
  for(let i=0;i<chain.length;i++){
   const r=chain[i];
   for(const value of [r.from,r.to]){const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw new Error('Invalid frozen redirect URL');}
   if(![301,302,303,307,308].includes(r.status)||r.from===r.to||r.to!==(chain[i+1]?.from||asset.url))throw new Error('Invalid frozen redirect sequence');
   if(assets.has(r.from)){
    // The same recorded URL can return a body and a cookie-dependent redirect.
    // Block that URL, not the entire document; never choose a body or hop.
    const body=assets.get(r.from),variants=ambiguous.get(r.from)||[{kind:'resource_body',sha256:body.sha256,mime:body.mime,http_status:body.http_status}];
    if(!variants.some(v=>JSON.stringify(v)===JSON.stringify(r)))variants.push(r);
    ambiguous.set(r.from,variants);redirects.delete(r.from);continue;
   }
   // A cookie-dependent URL can have multiple recorded destinations. Never
   // pick one or send live traffic: block that URL and expose all variants.
   const variants=ambiguous.get(r.from);
   if(variants){if(!variants.some(v=>JSON.stringify(v)===JSON.stringify(r)))variants.push(r);continue;}
   if(redirects.has(r.from)&&JSON.stringify(redirects.get(r.from))!==JSON.stringify(r)){
    ambiguous.set(r.from,[redirects.get(r.from),r]);redirects.delete(r.from);continue;
   }
   redirects.set(r.from,r);
  }
  }
 }
 Object.defineProperty(redirects,'ambiguous',{value:ambiguous});
 return redirects;
}
module.exports={VERSION,capture,index};
