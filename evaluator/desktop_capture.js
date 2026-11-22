'use strict';
const fs=require('node:fs'),path=require('node:path');
const VERSION='desktop-viewport-segments-v12';
const {visibleImagesSettled}=require('./visible_images');
async function prepare(page){
 await page.waitForFunction(()=>!document.fonts || document.fonts.status==='loaded',{},{timeout:15000});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 // Warm the exact scroll positions used by capture before the measurement
 // reference is frozen. CSS snapping and nested carousel scroll callbacks can
 // otherwise settle for the first time during the first screenshot traversal.
 const initial=await page.evaluate(()=>({x:scrollX,y:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight}));
 const imageWaitStarted=Date.now(),imageDeadline=imageWaitStarted+30000,pendingSegments=[];
 const lanes=await page.evaluateHandle(()=>[...document.querySelectorAll('*')].filter(e=>{
  const s=getComputedStyle(e);return e!==document.documentElement&&e!==document.body&&((['auto','scroll','hidden'].includes(s.overflowX)&&e.clientWidth>0&&e.scrollWidth>e.clientWidth)||(['auto','scroll','hidden'].includes(s.overflowY)&&e.clientHeight>0&&e.scrollHeight>e.clientHeight))&&e.querySelector('img[loading="lazy"]');
 }).map(node=>({node,x:node.scrollLeft,y:node.scrollTop})));
 const laneCount=await lanes.evaluate(rows=>rows.length),laneAxes=await lanes.evaluate(rows=>({horizontal:rows.filter(({node:e})=>['auto','scroll','hidden'].includes(getComputedStyle(e).overflowX)&&e.scrollWidth>e.clientWidth).length,vertical:rows.filter(({node:e})=>['auto','scroll','hidden'].includes(getComputedStyle(e).overflowY)&&e.scrollHeight>e.clientHeight).length})),pendingLanes=[];
 try{
  for(let index=0;index<Math.min(32,laneCount)&&Date.now()<imageDeadline;index++){
   const lane=await lanes.evaluate((rows,index)=>{const e=rows[index].node;if(!e.isConnected)return null;e.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});const s=getComputedStyle(e),scrollable=value=>['auto','scroll','hidden'].includes(value);return {width:e.clientWidth,height:e.clientHeight,extent:scrollable(s.overflowX)?Math.max(0,e.scrollWidth-e.clientWidth):0,vertical:scrollable(s.overflowY)?Math.max(0,e.scrollHeight-e.clientHeight):0,rtl:s.direction==='rtl',x:rows[index].x,y:rows[index].y};},index);
   if(!lane)continue;
   const positions=[];
   if(lane.extent>0)for(let step=0;step<=Math.min(100,Math.ceil(lane.extent/lane.width));step++)positions.push({left:(lane.rtl?-1:1)*Math.min(lane.extent,step*lane.width),top:lane.y});
   if(lane.vertical>0)for(let step=0;step<=Math.min(100,Math.ceil(lane.vertical/lane.height));step++)positions.push({left:lane.x,top:Math.min(lane.vertical,step*lane.height)});
   if(positions.length>101)pendingLanes.push({index,reason:'container_step_limit'});
   for(let step=0;step<Math.min(101,positions.length)&&Date.now()<imageDeadline;step++){
    await lanes.evaluate((rows,{index,left,top})=>rows[index].node.scrollTo({left,top,behavior:'instant'}),{index,...positions[step]});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const remaining=imageDeadline-Date.now();if(remaining<=0)break;
    await page.waitForFunction(visibleImagesSettled,{},{timeout:Math.min(1500,remaining)}).catch(()=>pendingLanes.push({index,step}));
   }
  }
 }finally{
  await lanes.evaluate(rows=>{for(const {node,x,y}of rows)if(node.isConnected)node.scrollTo({left:x,top:y,behavior:'instant'});});
  await lanes.dispose();
  await page.evaluate(p=>scrollTo({left:p.x,top:p.y,behavior:'instant'}),initial);
 }
 let count=Math.min(100,Math.max(1,Math.ceil(initial.height/initial.viewport)));
 try{
  for(let index=0;index<count;index++){
   await page.evaluate(y=>scrollTo({left:0,top:y,behavior:'instant'}),index*initial.viewport);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   // Native loading=lazy images can cancel/defer loading again when their
   // segment leaves the viewport. Settle each visible segment before leaving,
   // with one shared bounded budget; never rewrite authored loading attributes.
   const remaining=imageDeadline-Date.now();
   if(remaining>0){
    await page.waitForFunction(visibleImagesSettled,{},{timeout:Math.min(1500,remaining)}).catch(()=>pendingSegments.push(index));
   }else pendingSegments.push(index);
   const height=await page.evaluate(()=>document.documentElement.scrollHeight);
   count=Math.min(100,Math.max(count,Math.ceil(height/initial.viewport)));
  }
 }finally{
  await page.evaluate(p=>scrollTo({left:p.x,top:p.y,behavior:'instant'}),initial);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 }
 return {version:VERSION,applied:false,viewport:page.viewportSize(),font_wait_ms:15000,prepared_segments:count,initial_scroll:[initial.x,initial.y],segment_preparation_ms:Date.now()-imageWaitStarted,image_settlement_budget_ms:30000,pending_image_segments:pendingSegments,horizontal_image_lanes:laneAxes.horizontal,vertical_image_lanes:laneAxes.vertical,maximum_scrollable_image_containers:32,scrollable_image_containers:laneCount,scrollable_image_container_axes:'horizontal_and_vertical',maximum_horizontal_image_lanes:32,pending_image_lanes:pendingLanes};
}
async function capture(page,filename,quality=76){
 const initial=await page.evaluate(()=>({x:scrollX,y:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight}));
 const segments=[];const count=Math.min(100,Math.max(1,Math.ceil(initial.height/initial.viewport)));
 try{
  for(let index=0;index<count;index++){
   await page.evaluate(y=>scrollTo({left:0,top:y,behavior:'instant'}),index*initial.viewport);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const observed=await page.evaluate(()=>({x:scrollX,y:scrollY,width:innerWidth,height:innerHeight}));
   const target=index===0?filename:path.join(path.dirname(filename),path.basename(filename,path.extname(filename))+'.segment-'+index+'.jpg');
   // Playwright's default caret hiding rewrites inline styles on inputs,
   // serializing equivalent colors and invalidating the captured DOM.
   // Preserve the page's caret and complete authored attributes instead.
   await page.screenshot({path:target,type:'jpeg',quality,fullPage:false,caret:'initial'});
   segments.push({path:target,...observed});
  }
 }finally{
  await page.evaluate(p=>scrollTo({left:p.x,top:p.y,behavior:'instant'}),initial);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 }
 const metadata={version:VERSION,mode:'desktop_viewport_segments',document_height:initial.height,
  complete:initial.height<=count*initial.viewport,maximum_segments:100,segments,initial_scroll:[initial.x,initial.y]};
 fs.writeFileSync(filename+'.segments.json',JSON.stringify(metadata));return metadata;
}
module.exports={VERSION,prepare,capture};
