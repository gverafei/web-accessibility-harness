'use strict';
const VERSION='frozen-resource-settlement-v2';
async function settleDocument(page, tracker) {
 // document.write returns while external/deferred scripts can still be loading.
 // Lazy exploration must see the initialized layout and its scroll listeners.
 await page.waitForFunction(() => document.readyState !== 'loading', null, {timeout:45000});
 return tracker.settle();
}
function track(page,registered){
 const pending=new Map();let changed=Date.now();
 const start=request=>{if(registered(request)){pending.set(request,{url:request.url(),type:request.resourceType()});changed=Date.now();}};
 const end=request=>{if(pending.delete(request))changed=Date.now();};
 const detached=frame=>{for(const request of pending.keys()){let owner;try{owner=request.frame();}catch{continue;}if(owner===frame)end(request);}};
 page.on('request',start);page.on('requestfinished',end);page.on('requestfailed',end);page.on('framedetached',detached);
 return {async settle(timeout=45000,quiet=500){
  const started=Date.now();
  while(Date.now()-started<timeout){
   if(!pending.size&&Date.now()-changed>=quiet)return {version:VERSION,status:'settled',wait_ms:Date.now()-started,pending:[]};
   await new Promise(resolve=>setTimeout(resolve,50));
  }
  const error=new Error('Frozen resource settlement timed out');
  error.settlement={version:VERSION,status:'timeout',pending:[...pending.values()],wait_ms:Date.now()-started};throw error;
 },dispose(){page.off('request',start);page.off('requestfinished',end);page.off('requestfailed',end);page.off('framedetached',detached);}};
}
module.exports={VERSION,track,settleDocument};
