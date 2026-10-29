'use strict';
const crypto=require('node:crypto');
const VERSION='same-document-phase-evidence-v12';
const hashBindings=new WeakSet();
async function observe(page,phase){
 if(typeof page.exposeFunction==='function'&&!hashBindings.has(page)){await page.exposeFunction('__harnessHashCss',value=>crypto.createHash('sha256').update(value).digest('hex'));hashBindings.add(page);}
 const serialized=await page.evaluate(async()=>{
  // Large repeated data URLs/custom properties otherwise duplicate megabytes
  // per node and per phase across the browser protocol. Hash complete values,
  // never truncate their fingerprint; the source document remains preserved.
  const largeValues=new Map();
  async function compact(value){
   if(typeof value!=='string'||value.length<=1024)return value;
   if(!largeValues.has(value))largeValues.set(value,(crypto.subtle?crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)).then(bytes=>Array.from(new Uint8Array(bytes),n=>n.toString(16).padStart(2,'0')).join('')):window.__harnessHashCss(value)).then(sha256=>({sha256,characters:value.length})));
   return largeValues.get(value);
  }
  // Cloning in the live document upgrades custom elements and can run their
  // constructors/attribute callbacks (e.g. Astro islands reinitializing Swiper).
  // Import into a document with no browsing context/custom-element registry.
  const inert=document.implementation.createHTMLDocument('');
  const clone=inert.importNode(document.documentElement,true);
  const resourceHints=[];
  for(const hint of clone.querySelectorAll('head link')){
   const rel=hint.getAttribute('rel')?.trim().toLowerCase();
   if(rel==='prefetch'||rel==='modulepreload'||(rel==='preload'&&hint.getAttribute('as')?.toLowerCase()==='script')){
    resourceHints.push({rel,as:hint.getAttribute('as'),href:hint.getAttribute('href')});hint.remove();
   }
  }
  // Axe injects scripts; executable text is not rendered evidence. Retain
  // all style elements, attributes, text and native control values.
  for(const script of clone.querySelectorAll('script'))script.remove();
  // DOM classList order is not content. Computed geometry/paint still detects
  // effects of order-sensitive attribute selectors on the live document.
  for(const e of [clone,...clone.querySelectorAll('[class]')])if(e.hasAttribute('class'))e.setAttribute('class',Array.from(new Set(e.getAttribute('class').split(/\s+/).filter(Boolean))).sort().join(' '));
  // Screenshot caret restoration can leave style="" on an input.
  // Normalize only empty declarations; full computed styles still detect
  // selector effects (including [style]) and nonempty changes remain in DOM.
  for(const e of [clone,...clone.querySelectorAll('[style]')])if(e.hasAttribute('style')&&!e.style.cssText)e.removeAttribute('style');
  const elements=Array.from(document.querySelectorAll('*'));
  const styles=[],cssProperties=[],cssIndex=new Map();
  async function internProperty(key,value){
   const pair=[key,await compact(value)],serialized=JSON.stringify(pair);
   if(!cssIndex.has(serialized)){cssIndex.set(serialized,cssProperties.length);cssProperties.push(pair);}
   return cssIndex.get(serialized);
  }
  for(const e of elements.filter(e=>!['SCRIPT','STYLE','META','LINK','HEAD','TITLE'].includes(e.tagName))){
   const s=getComputedStyle(e),r=e.getBoundingClientRect();
   styles.push([e.tagName,s.display,s.visibility,s.color,s.backgroundColor,await compact(s.backgroundImage),
    s.fontFamily,s.fontSize,s.fontWeight,s.position,s.opacity,
    ...[r.x,r.y,r.width,r.height].map(n=>Math.round(n*10)/10),
    e.value===undefined?null:e.value,e.checked===undefined?null:e.checked,
    e.indeterminate===undefined?null:e.indeterminate,e.tagName==='SELECT'?[...e.options].flatMap((option,index)=>option.selected?[index]:[]):null,
    e.tagName==='IMG'?[e.currentSrc,e.complete,e.naturalWidth,e.naturalHeight]:null,
    await Promise.all(['outline-color','outline-style','outline-width','outline-offset','transform','filter','clip-path','border-top-width','border-bottom-width','border-left-width','border-right-width','text-decoration-line','line-height','letter-spacing','background-position','background-size','background-repeat','box-shadow','text-shadow','overflow-x','overflow-y','fill','stroke','stroke-width','border-top-color','border-bottom-color','border-left-color','border-right-color'].map(key=>internProperty(key,s.getPropertyValue(key))))]);
  }
  // One JSON string avoids Playwright serializing every nested CSS pair as a
  // separate protocol object. Values and diagnostic properties stay complete.
  return JSON.stringify({origin:location.origin,url:location.href,base:document.baseURI,
   viewport:[innerWidth,innerHeight],scroll:[scrollX,scrollY],html:clone.outerHTML,styles,cssProperties,resourceHints,domEntries:[clone,...clone.querySelectorAll('*')].map(e=>[e.tagName,Array.from(e.attributes).map(a=>[a.name,a.value]),Array.from(e.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent)] )});
 });
 const state=typeof serialized==='string'?JSON.parse(serialized):serialized;
 if(state.cssProperties){
  for(const row of state.styles)row[row.length-1]=row.at(-1).map(index=>state.cssProperties[index]);
  delete state.cssProperties;
 }
 const resourceHints=state.resourceHints||[];delete state.resourceHints;
 const domEntries=state.domEntries;delete state.domEntries;
 const diagnosticStyles=state.styles;
 // Relevant computed painting/typography properties remain diagnostic.
 // Original authored CSS is retained in the frozen resources/DOM; enumerating
 // every unrelated resolved property per SVG node adds no admission evidence.
 state.styles=state.styles.map(row=>[...row.slice(0,-1),row.at(-1).filter(([key])=>['outline-color','outline-style','outline-width','outline-offset','transform','filter','clip-path','border-top-width','border-bottom-width','border-left-width','border-right-width','text-decoration-line','line-height','letter-spacing'].includes(key))]);
 const hash=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
 const result={phase,version:VERSION,sha256:hash(state),dom_sha256:hash(state.html),
  layout_sha256:hash(state.styles),viewport:state.viewport,scroll:state.scroll,
  origin:state.origin,url:state.url,resource_hints:resourceHints,node_count:state.styles.length};
 Object.defineProperty(result,"layoutEntries",{value:diagnosticStyles});Object.defineProperty(result,"domEntries",{value:domEntries});return result;
}
function entryChanges(before,after){
 const count=entries=>{const result=new Map();for(const entry of entries||[]){const key=JSON.stringify(entry);const old=result.get(key);result.set(key,{entry,count:(old?.count||0)+1});}return result;};
 const a=count(before),b=count(after),added=[],removed=[];
 for(const [key,item] of b){const delta=item.count-(a.get(key)?.count||0);if(delta>0&&added.length<20)added.push({entry:item.entry,count:delta});}
 for(const [key,item] of a){const delta=item.count-(b.get(key)?.count||0);if(delta>0&&removed.length<20)removed.push({entry:item.entry,count:delta});}
 return {added,removed};
}
function summarize(phases){
 const differences=phases.slice(1).map(p=>({phase:p.phase,entries:(p.layoutEntries||[]).flatMap((entry,index)=>JSON.stringify(entry)===JSON.stringify(phases[0].layoutEntries?.[index])?[]:[{index,before:phases[0].layoutEntries?.[index],after:entry}]).slice(0,20)}));
 const dom_differences=phases.slice(1).map(p=>({phase:p.phase,entries:(p.domEntries||[]).flatMap((entry,index)=>JSON.stringify(entry)===JSON.stringify(phases[0].domEntries?.[index])?[]:[{index,before:phases[0].domEntries?.[index],after:entry}]).slice(0,20)}));
  return {dom_changes:phases.slice(1).map(p=>({phase:p.phase,...entryChanges(phases[0].domEntries,p.domEntries)})),box_normalization:'actual-geometry-paint-state-v3',dom_normalization:'inert-document-empty-style-head-script-hints-v3',dom_differences,differences,version:VERSION,stable:phases.length>=4&&phases.every(p=>p.sha256===phases[0].sha256),phases,
  scope:'Admission: DOM, origin, viewport, actual geometry, primary painting/typography, native state and image identity. Relevant computed CSS differences diagnostic; authored CSS retained in source/resources. Not pixel or interaction equivalence'};
}
module.exports={VERSION,observe,summarize};
