'use strict';
// Read the response from this navigation's CDP buffer, never another GET or DOM.
function collect(session){
 const documents=new Map();
 session.on('Network.responseReceived',event=>{
  if(event.type!=='Document')return;
  let resolve;const promise=new Promise(done=>resolve=done);
  documents.set(event.requestId,{url:event.response.url,promise,resolve});
 });
 session.on('Network.loadingFailed',event=>documents.get(event.requestId)?.resolve(null));
 session.on('Network.loadingFinished',async event=>{
  const item=documents.get(event.requestId);if(!item)return;
  try{
   const result=await session.send('Network.getResponseBody',{requestId:event.requestId});
   const body=result.base64Encoded?Buffer.from(result.body,'base64').toString('utf8'):result.body;
   item.resolve(body&&Buffer.byteLength(body)<=require('./evidence_limits').DOCUMENT_BYTES?body:null);
  }catch{item.resolve(null);}
 });
 return {async read(url){
  const item=[...documents.values()].filter(d=>d.url===url).at(-1);if(!item)return null;
  let timer;try{return await Promise.race([item.promise,new Promise(resolve=>timer=setTimeout(()=>resolve(null),15000))]);}finally{clearTimeout(timer);}
 }};
}
module.exports={collect};
