'use strict';
const crypto=require('node:crypto');
const VERSION='observed-native-control-state-v1';

// These are browser properties, not necessarily reflected in page.content().
// Keep the original HTML intact and never infer state from a screenshot.
function inspect(reference){
 const canonical=value=>{const normalize=v=>Array.isArray(v)?v.map(normalize):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,normalize(v[k])])):v;return JSON.stringify(normalize(value));};
 const path=el=>{const parts=[];for(let n=el;n;n=n.parentElement){const siblings=n.parentElement?[...n.parentElement.children].filter(x=>x.tagName===n.tagName):[n];parts.unshift(n.localName+':nth-of-type('+(siblings.indexOf(n)+1)+')');}return parts.join(' > ');};
 const flags=['disabled','required','multiple','checked','selected','readonly'];
 const attrs=el=>['name','type','value','form','action','method','enctype','target','formaction','formmethod','formenctype','formtarget','min','max','step','minlength','maxlength','pattern','accept',...flags].map(k=>{
  let value=flags.includes(k)?el.hasAttribute(k):el.getAttribute(k);
  if(['action','formaction'].includes(k)&&value!==null){try{value=new URL(value,document.baseURI).href;}catch{/* Retain unresolved declared evidence, e.g. an inert about:blank fixture. */}}
  if(['type','method','enctype','formmethod','formenctype'].includes(k)&&typeof value==='string')value=value.toLowerCase();
  return [k,value];
 });
 const signature=el=>({tag:el.localName,attributes:attrs(el),owner:el.form?{id:el.form.id,path:path(el.form),attributes:attrs(el.form)}:null,
  options:el.localName==='select'?[...el.options].map(o=>({attributes:attrs(o),text:o.textContent})):null,
  text:el.localName==='textarea'?el.textContent:null,effective_disabled:el.matches(':disabled')});
 const controls=[...document.querySelectorAll('input,select,textarea,button')];
 const read=el=>el.localName==='select'?{value:el.value,selected_indexes:[...el.options].flatMap((o,i)=>o.selected?[i]:[])}:
  el.localName==='input'?{value:el.value,checked:el.checked,indeterminate:el.indeterminate}: {value:el.value};
 if(!reference)return controls.map(el=>({id:el.id||null,path:path(el),signature:signature(el),state:read(el),
  restorable:!(el.localName==='input'&&el.type==='file'&&(el.files.length||el.value))}));
 const results=[];
 for(const record of reference.records){
  const matches=record.id?[...document.querySelectorAll('[id]')].filter(el=>el.id===record.id):controls.filter(el=>path(el)===record.path);
  if(matches.length!==1||!controls.includes(matches[0])){results.push({path:record.path,status:'not_matched',reason:'Native control identity is missing or ambiguous'});continue;}
  const el=matches[0];
  if(canonical(signature(el))!==canonical(record.signature)){results.push({path:record.path,status:'not_matched',reason:'Declared native control or form contract changed'});continue;}
  if(!record.restorable){results.push({path:record.path,status:'unavailable',reason:'A native file selection cannot be reconstructed'});continue;}
  const state=record.state;
  if(el.localName==='select'){
   for(const [index,option] of [...el.options].entries())option.selected=state.selected_indexes.includes(index);
   if(!state.selected_indexes.length)el.selectedIndex=-1;
  }else if(el.localName==='input'){
   // Setting even an unchanged checkbox/button value can create a value
   // attribute. Preserve the original serialized DOM as well as its state.
   if(el.value!==state.value)el.value=state.value;
   el.checked=state.checked;el.indeterminate=state.indeterminate;
  }else if(el.value!==state.value)el.value=state.value;
  results.push({path:record.path,status:canonical(read(el))===canonical(state)?'restored':'failed'});
 }
 return results;
}
async function capture(page){
 const html=await page.content(),records=await page.evaluate(inspect);
 if(await page.content()!==html)throw Error('Native control observation changed document');
 return {version:VERSION,document_sha256:crypto.createHash('sha256').update(html).digest('hex'),records,
  scope:'Observed native values, option selections, checked and indeterminate properties; no event handlers or task success inferred'};
}
function validate(reference){
 if(!reference||reference.version!==VERSION||!Array.isArray(reference.records))throw Error('Invalid native control reference');
 for(const r of reference.records){
  if(!r||typeof r.path!=='string'||!r.signature||!['input','select','textarea','button'].includes(r.signature.tag)||typeof r.restorable!=='boolean'||typeof r.state?.value!=='string')throw Error('Invalid native control state');
  if(r.signature.tag==='select'){
   const indexes=r.state.selected_indexes;
   if(!Array.isArray(r.signature.options)||!Array.isArray(indexes)||new Set(indexes).size!==indexes.length||indexes.some(i=>!Number.isInteger(i)||i<0||i>=r.signature.options.length))throw Error('Invalid native option selection');
  }else if(r.signature.tag==='input'&&(typeof r.state.checked!=='boolean'||typeof r.state.indeterminate!=='boolean'))throw Error('Invalid native checked state');
 }
}
async function restore(page,reference){
 if(!reference)return {version:VERSION,status:'not_recorded',results:[],scope:'Legacy capture has no observed native control reference; no state invented'};
 validate(reference);
 const results=await page.evaluate(inspect,reference);
 return {version:VERSION,status:results.some(x=>x.status==='failed')?'failed':results.every(x=>x.status==='restored')?'completed':'partial',results,
  scope:'Restore only recorded browser properties on unique controls with unchanged declared contracts; no events dispatched or model changes overwritten'};
}
module.exports={VERSION,capture,restore,validate};
