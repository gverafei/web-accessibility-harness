// Presentation only. Retain actor DOM identity; animate actual changes, never infer work.
(()=>{
 window.liveStageRoute=(nodes,from,to)=>{
  const a=nodes[from],b=nodes[to];if(!a||!b||from===to)return null;
  const adjacent=[['context','evidence'],['evidence','selection'],['selection','repair'],['repair','audit'],['audit','taxonomy'],['taxonomy','preserve'],['preserve','retain']].some(pair=>(pair[0]===from&&pair[1]===to)||(pair[0]===to&&pair[1]===from));
  if(adjacent&&Math.abs(a.y-b.y)<30){const direction=Math.sign(b.x-a.x);return `M${a.x+direction*a.rx} ${a.y}H${b.x-direction*b.rx}`;}
  if(adjacent&&Math.abs(a.x-b.x)<30){const direction=Math.sign(b.y-a.y);return `M${a.x} ${a.y+direction*a.ry}V${b.y-direction*b.ry}`;}
  // Side ports and an outer lane avoid every intervening stage and its label.
  const direction=Math.sign(b.x-a.x)||1,lane=a.y>200&&b.y>200?390:10;
  const source=a.x+direction*a.rx,target=b.x-direction*b.rx;
  const depart=source+direction*18,arrive=target-direction*18;
  return `M${source} ${a.y}H${depart}V${lane}H${arrive}V${b.y}H${target}`;
 };
 const reduced=()=>window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
 window.prepareLiveMotion=(oldRoot,nextRoot)=>{
  const old=oldRoot?.querySelector('[data-live-loop]'),next=nextRoot?.matches?.('[data-live-loop]')?nextRoot:nextRoot?.querySelector('[data-live-loop]');if(!next)return;
  const changed=old?.dataset.flowRevision!==next.dataset.flowRevision;
  if(changed)next.classList.add('is-new-activity');
  if(old?.dataset.activeNode!==next.dataset.activeNode||['refine','rollback','accepted'].includes(next.dataset.eventKind))next.classList.add('is-stage-transfer');
  next.dataset.previousStage=old?.dataset.activeNode||'';
  if(old?.dataset.activeNode===next.dataset.activeNode){const key=next.dataset.activeNode;const ring=old.querySelector(`[data-live-stage="${key}"] .live-stage-ring`),updated=next.querySelector(`[data-live-stage="${key}"] .live-stage-ring`);if(ring&&updated){ring.className=updated.className;ring.setAttribute('style',updated.getAttribute('style'));updated.replaceWith(ring);}const meter=old.querySelector(`[data-live-participant="${key}"] .invocation-meter`),newMeter=next.querySelector(`[data-live-participant="${key}"] .invocation-meter`);if(meter&&newMeter)newMeter.replaceWith(meter);}
  next.querySelectorAll('[data-actor-key]').forEach(actor=>{
   const stage=actor.closest('[data-live-stage]').dataset.liveStage;
   const previous=Array.from(old?.querySelectorAll('[data-actor-key]')||[]).find(a=>a.dataset.actorKey===actor.dataset.actorKey&&a.closest('[data-live-stage]').dataset.liveStage===stage);
   if(previous){const called=previous.dataset.liveActor!==actor.dataset.liveActor;previous.innerHTML=actor.innerHTML;previous.dataset.liveActor=actor.dataset.liveActor;previous.dataset.actorCalls=actor.dataset.actorCalls;actor.replaceWith(previous);if(called&&!reduced())previous.animate([{filter:'brightness(1)',boxShadow:'0 0 5px currentColor'},{filter:'brightness(1.5)',boxShadow:'0 0 22px currentColor'},{filter:'brightness(1)',boxShadow:'0 0 5px currentColor'}],{duration:1100});}
   else actor.classList.add('is-new-actor');
  });
  next.querySelectorAll('[data-live-participant]').forEach(row=>{const prior=old?.querySelector(`[data-live-participant="${row.dataset.liveParticipant}"]`);if(prior&&prior.dataset.stageCalls!==row.dataset.stageCalls)row.classList.add('is-invoked');});
 };
 window.alignLiveMotion=(root=document)=>{
  root.querySelectorAll('[data-live-loop]').forEach(panel=>{
   const svg=panel.querySelector('.live-loop-links');if(!svg)return;const bounds=svg.getBoundingClientRect();if(!bounds.width||!bounds.height)return;
   svg.querySelectorAll('.live-revisit,.live-revisit-label').forEach(node=>node.remove());
   const nodes={};panel.querySelectorAll('[data-live-stage]').forEach(node=>{const r=node.getBoundingClientRect();nodes[node.dataset.liveStage]={x:(r.left+r.width/2-bounds.left)*1000/bounds.width,y:(r.top+r.height/2-bounds.top)*400/bounds.height,rx:(r.width/2+14)*1000/bounds.width,ry:(r.height/2+14)*400/bounds.height};});
   const route=(from,to)=>window.liveStageRoute(nodes,from,to);
   const pairs=[['context','evidence'],['evidence','selection'],['selection','repair'],['repair','audit'],['audit','taxonomy'],['taxonomy','preserve'],['preserve','retain']];
   const paths=svg.querySelectorAll('path:not(defs path):not(.packet-page):not(.packet-fold):not(.packet-code):not(.live-loop-return):not(.live-loop-accepted):not(.live-revisit)');pairs.forEach((pair,i)=>{if(paths[i]){paths[i].setAttribute('d',route(...pair));paths[i].setAttribute('data-transfer-active','false');}});
   let from=panel.dataset.previousStage,to=panel.dataset.activeNode,travel=route(from,to);
   if(panel.dataset.eventKind==='refine'||panel.dataset.eventKind==='rollback'){
    const a=nodes.retain,b=nodes.context;travel=`M${a.x-a.rx} ${a.y}H15V${b.y}H${b.x-b.rx}`;svg.querySelector('.live-loop-return')?.setAttribute('d',travel);
   }else if(panel.dataset.eventKind==='accepted'){
    const a=nodes.retain;travel=`M${a.x} ${a.y+a.ry}V390H${a.x+110}`;svg.querySelector('.live-loop-accepted')?.setAttribute('d',travel);
   }else if(travel&&from&&from!==to){
    const connection=pairs.findIndex(p=>(p[0]===from&&p[1]===to)||(p[0]===to&&p[1]===from));
    if(connection>=0){paths[connection]?.setAttribute('data-transfer-active','true');}
    else{
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('class','live-revisit');path.setAttribute('d',travel);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`${panel.querySelector(`[data-live-stage="${from}"] strong`)?.textContent} → ${panel.querySelector(`[data-live-stage="${to}"] strong`)?.textContent}`;path.append(title);svg.append(path);
    }
   }
   const packet=svg.querySelector('.live-event-packet');if(packet&&travel)packet.style.offsetPath=`path("${travel}")`;
  });
 };
 window.addEventListener('resize',()=>window.alignLiveMotion());window.alignLiveMotion();
})();
