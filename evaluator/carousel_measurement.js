'use strict';
const VERSION='caroufredsel-measurement-state-v1';
async function prepare(page){
 const widgets=await page.evaluate(()=>{
  const $=window.jQuery;
  if(!$||!$.fn||typeof $.fn.carouFredSel!=='function')return [];
  const result=[];
  // Only initialized library instances expose this registered API. Authored
  // lookalike classes and other carousel implementations remain untouched.
  for(const element of document.querySelectorAll('.caroufredsel_wrapper > *')){
   const widget=$(element);
   if(widget.data('_cfs_isCarousel')!==true)continue;
   const call=(name,args=[])=>widget.triggerHandler('_cfs_triggerEvent',[name,args]);
   const before=call('currentPosition');
   if(!Number.isInteger(before)||before<0)throw Error('Unsupported carouFredSel position');
   const children=[...element.children];
   call('configuration',['auto.play',false,false]);
   call('finish');call('pause',[true]);
   call('slideTo',[0,0,true,{duration:0}]);call('finish');call('pause',[true]);
   const after=call('currentPosition'),paused=call('isPaused');
   if(after!==0||paused!==true||element.children.length!==children.length||children.some(child=>child.parentElement!==element)){
    throw Error('carouFredSel measurement state could not be established without content loss');
   }
   result.push({position_before:before,position_after:after,paused,items:children.length});
  }
  return result;
 });
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 return {version:VERSION,scope:'Canonical first item for initialized carouFredSel; content and controls retained',widgets};
}
module.exports={VERSION,prepare};
