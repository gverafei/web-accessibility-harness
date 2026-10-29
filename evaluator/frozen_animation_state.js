'use strict';
const VERSION='observed-css-animation-state-v1';
// Executed unchanged in both realms: identity comes from actual browser effects.
function observe(){
 const path=e=>{const parts=[];for(let n=e;n&&n!==document.documentElement;n=n.parentElement){if(!n.parentElement)return null;const peers=[...n.parentElement.children].filter(p=>p.tagName===n.tagName);parts.unshift(n.tagName.toLowerCase()+':nth-of-type('+(peers.indexOf(n)+1)+')');}return 'html > '+parts.join(' > ');};
 return document.getAnimations().filter(a=>a instanceof CSSAnimation&&a.timeline instanceof DocumentTimeline&&a.effect?.target instanceof Element).map(a=>({
  version:'observed-css-animation-state-v1',path:path(a.effect.target),name:a.animationName,pseudo:a.effect.pseudoElement||null,
  time:a.currentTime,paused:a.playState==='paused',keyframes:a.effect.getKeyframes(),
  timing:Object.fromEntries(Object.entries(a.effect.getTiming()).map(([k,v])=>[k,v===Infinity?'Infinity':v]))
 }));
}
async function capture(page){return page.evaluate(observe);}
async function restore(page,references=[]){
 const path=/^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9]\d*\))+$/;
 const valid=references.filter(r=>r?.version===VERSION&&path.test(r.path)&&typeof r.name==='string'&&r.name&&r.paused===true&&typeof r.time==='number'&&Number.isFinite(r.time)&&r.time>=0&&r.time<=31536000000&&Array.isArray(r.keyframes)&&r.timing&&typeof r.timing==='object');
 const observed=await capture(page);
 const result=await page.evaluate(({valid,observed})=>{
  const stable=v=>JSON.stringify(sort(v));function sort(v){if(Array.isArray(v))return v.map(sort);if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])]));return v;}
  const identity=r=>stable({path:r.path,name:r.name,pseudo:r.pseudo||null,keyframes:r.keyframes,timing:r.timing});
  const animations=document.getAnimations().filter(a=>a instanceof CSSAnimation&&a.timeline instanceof DocumentTimeline&&a.effect?.target instanceof Element);
  const results=[];
  for(const r of valid){const key=identity(r),matches=observed.map((o,i)=>identity(o)===key?i:-1).filter(i=>i>=0);
   if(matches.length!==1||valid.filter(o=>identity(o)===key).length!==1){results.push({path:r.path,name:r.name,status:'unmatched_reference'});continue;}
   const a=animations[matches[0]];try{a.pause();a.currentTime=r.time;if(a.currentTime!==r.time)throw Error('Observed time not restored');results.push({path:r.path,name:r.name,time:a.currentTime,status:'restored'});}catch(e){results.push({path:r.path,name:r.name,status:'failed',error:e.message});}
  }
  return results;
 },{valid,observed});
 // Resolve compositor changes before visible evidence; no DOM/style rewrite.
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 return {version:VERSION,eligible:valid.length,results:result};
}
module.exports={VERSION,capture,restore};
