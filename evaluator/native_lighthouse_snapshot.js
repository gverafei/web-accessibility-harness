'use strict';
async function snapshot(page,port){
 if(!Number.isInteger(port)||port<1||port>65535)throw Error('Native snapshot debugging port unavailable');
 const session=await page.context().newCDPSession(page);
 const {targetInfo}=await session.send('Target.getTargetInfo');
 await session.detach();
 const connection=await require('puppeteer-core').connect({browserURL:'http://127.0.0.1:'+port,defaultViewport:null});
 try{
  let target;
  for(const item of await connection.pages()){
   const probe=await item.createCDPSession();
   const info=await probe.send('Target.getTargetInfo');await probe.detach();
   if(info.targetInfo.targetId===targetInfo.targetId){target=item;break;}
  }
  if(!target)throw Error('Native snapshot did not find acquired document');
  const raw=(await require('./axe_name_guard').lighthouse().snapshot(target,{flags:{onlyCategories:['accessibility'],logLevel:'error',...require('./desktop_profile').lighthouseFlags(true)}})).lhr;
  return {summary:{accessibility_score:require('./lighthouse_score').extractAccessibilityScore(raw)},raw,mode:'snapshot'};
 }finally{await connection.disconnect();}
}
module.exports={snapshot};
