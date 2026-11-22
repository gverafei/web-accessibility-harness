'use strict';
const VERSION='auditor-scroll-restoration-v3';
async function capture(page){
 return page.evaluate(()=>{
  const nodes=[];
  // content-visibility and inspection can activate a previously unlaid-out
  // scroll container. Keep every acquired offset; restore only changed ones.
  function visit(root){for(const node of root.querySelectorAll('*')){nodes.push({node,x:node.scrollLeft,y:node.scrollTop});if(node.shadowRoot)visit(node.shadowRoot);}}
  visit(document);window.__harnessAuditScroll={nodes,x:scrollX,y:scrollY};return {containers:nodes.length};
 });
}
async function restore(page){
 const result=await page.evaluate(()=>{
  const state=window.__harnessAuditScroll;if(!state)throw Error('Missing pre-audit scroll state');
  const changes=[];let detached=0;
  for(const {node,x,y}of state.nodes){if(!node.isConnected){detached++;continue;}if(node.scrollLeft!==x||node.scrollTop!==y){changes.push({tag:node.tagName,id:node.id,before:[x,y],after:[node.scrollLeft,node.scrollTop]});node.scrollTo({left:x,top:y,behavior:'instant'});}}
  scrollTo({left:state.x,top:state.y,behavior:'instant'});delete window.__harnessAuditScroll;
  return {changed_containers:changes,detached_containers:detached};
 });
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 return {version:VERSION,...result,scope:'Restore only auditor inspection scroll offsets; no DOM, styles, findings or control values rewritten. Document phase checks still enforce preservation.'};
}
module.exports={VERSION,capture,restore};
