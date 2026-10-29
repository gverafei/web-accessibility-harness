'use strict';
const crypto=require('node:crypto');
const VERSION='observed-semantic-state-v1';
async function collect(page){
 const before=await page.content();
 const elements=await page.evaluate(()=>{
  const path=el=>{const p=[];for(let n=el;n;n=n.parentElement){const same=n.parentElement?[...n.parentElement.children].filter(x=>x.tagName===n.tagName):[n];p.unshift(n.localName+':nth-of-type('+(same.indexOf(n)+1)+')');}return p.join(' > ');};
  const visible=el=>{if(!el)return null;const s=getComputedStyle(el);return s.display!=='none'&&s.visibility!=='hidden'&&s.visibility!=='collapse'&&el.getClientRects().length>0;};
  return [...document.querySelectorAll('[aria-expanded],[aria-selected],[aria-checked],[aria-pressed],[aria-errormessage]')].map(el=>({selector:path(el),tag:el.localName,
   checked:typeof el.checked==='boolean'?el.checked:null,indeterminate:typeof el.indeterminate==='boolean'?el.indeterminate:null,
   selected:typeof el.selected==='boolean'?el.selected:null,
   controlled:[...(el.getAttribute('aria-controls')||'').split(/\s+/).filter(Boolean)].map(id=>{const matches=[...document.querySelectorAll('[id]')].filter(x=>x.id===id);return {id,unique:matches.length===1,visible:matches.length===1?visible(matches[0]):null};}),
   validity:el.validity?{valid:el.validity.valid,valueMissing:el.validity.valueMissing,typeMismatch:el.validity.typeMismatch,patternMismatch:el.validity.patternMismatch,rangeUnderflow:el.validity.rangeUnderflow,rangeOverflow:el.validity.rangeOverflow}:null}));
 });
 if(await page.content()!==before)throw Error('Semantic observation changed document');
 return {version:VERSION,document_sha256:crypto.createHash('sha256').update(before).digest('hex'),elements};
}
module.exports={VERSION,collect};
