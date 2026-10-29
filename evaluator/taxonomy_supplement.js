'use strict';
const crypto=require('node:crypto');
const VERSION='rendered-taxonomy-supplement-v4';
function mediaTracks(body){
 const handlers=[];let movie=false;
 function boxes(start,end,depth){
  if(depth>8)throw Error('MP4 nesting bound');
  for(let p=start;p<end;){
   if(p+8>end)throw Error('Truncated MP4 box');
   let size=body.readUInt32BE(p),header=8;const type=body.toString('ascii',p+4,p+8);
   if(size===1){if(p+16>end)throw Error('Truncated extended box');const n=body.readBigUInt64BE(p+8);if(n>BigInt(Number.MAX_SAFE_INTEGER))throw Error('Oversized box');size=Number(n);header=16;}
   if(size===0)size=end-p;
   if(size<header||p+size>end)throw Error('Invalid MP4 box bound');
   if(type==='moov')movie=true;
   if(['moov','trak','mdia'].includes(type))boxes(p+header,p+size,depth+1);
   if(type==='hdlr'){if(size<header+12)throw Error('Truncated handler');handlers.push(body.toString('ascii',p+header+8,p+header+12));}
   p+=size;
  }
 }
 try{boxes(0,body.length,0);const known=handlers.every(x=>['vide','soun','text','subt','sbtl','meta','clcp'].includes(x));
  return {complete:movie&&handlers.includes('vide')&&known,handlers,audio_tracks:handlers.filter(x=>x==='soun').length,caption_tracks:handlers.filter(x=>['text','subt','sbtl','clcp'].includes(x)).length};
 }catch(e){return {complete:false,error:e.message,handlers};}
}
function rgb(s){const m=String(s).match(/^rgba?\(([^)]+)\)$/);if(!m)return null;const v=m[1].split(',').map(Number);return v.length>=3&&v.every(Number.isFinite)?[...v.slice(0,3),v.length===4?v[3]:1]:null;}
function ratio(a,b){const l=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);const x=l(a),y=l(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
function contrast(e){
 const fg=rgb(e.color);if(!fg||fg[3]!==1||!e.visible||e.occluded||e.paint_complex)return {status:'insufficient_evidence',reason:'Unresolved painted background, opacity, visibility or occlusion'};
 let bg=null;for(const layer of e.layers){const c=rgb(layer.backgroundColor);if(!c)return {status:'insufficient_evidence',reason:'Unsupported color syntax'};if(c[3]===1){bg=c;break;}if(c[3]!==0)return {status:'insufficient_evidence',reason:'Translucent background requires pixel evidence'};}
 if(!bg)return {status:'insufficient_evidence',reason:'No explicit opaque background'};
 const size=parseFloat(e.fontSize),bold=parseInt(e.fontWeight,10)>=700,threshold=size>=24||bold&&size>=18.666666?3:4.5;
 const measured=ratio(fg,bg);return {status:measured>=threshold?'passed':'failed',ratio:measured,threshold,foreground:fg,background:bg};
}
async function paintedContrast(page,selector,e,getPixelPage){
 const fg=rgb(e.color);if(!fg||fg[3]!==1||e.occluded||!e.visible||e.layers.some(l=>l.opacity!=='1'||l.filter!=='none'))return e.measurement;
 const token=await page.evaluate(selector=>{
  const old=[...document.adoptedStyleSheets],sheet=new CSSStyleSheet();
  sheet.replaceSync(`${selector},${selector} * {color:transparent!important;text-shadow:none!important;-webkit-text-stroke-color:transparent!important;}`);
  document.adoptedStyleSheets=[...old,sheet];return old.length;
 },selector);
 let png,unchanged,clip;
 try{
  unchanged=await page.locator(selector).evaluate(el=>{const rows=[];for(let n=el;n;n=n.parentElement){const s=getComputedStyle(n);rows.push({backgroundColor:s.backgroundColor,backgroundImage:s.backgroundImage});}return rows;});
  const viewport=await page.evaluate(()=>({x:scrollX,y:scrollY,width:innerWidth,height:innerHeight}));
  const visible=e.text_rects.filter(r=>r.width>0&&r.height>0&&r.x<viewport.width&&r.y<viewport.height&&r.x+r.width>0&&r.y+r.height>0);
  if(!visible.length)return {status:'insufficient_evidence',reason:'No visible text pixels'};
  const left=Math.max(0,Math.floor(Math.min(...visible.map(r=>r.x)))),top=Math.max(0,Math.floor(Math.min(...visible.map(r=>r.y))));
  const right=Math.min(viewport.width,Math.ceil(Math.max(...visible.map(r=>r.x+r.width)))),bottom=Math.min(viewport.height,Math.ceil(Math.max(...visible.map(r=>r.y+r.height))));
  clip={x:viewport.x+left,y:viewport.y+top,width:right-left,height:bottom-top,viewport_x:left,viewport_y:top};
  png=await page.screenshot({type:'png',caret:'initial',clip:{x:clip.viewport_x,y:clip.viewport_y,width:clip.width,height:clip.height}});
 }finally{await page.evaluate(n=>{document.adoptedStyleSheets=document.adoptedStyleSheets.slice(0,n);},token);}
 if(unchanged.some((x,i)=>x.backgroundColor!==e.layers[i].backgroundColor||x.backgroundImage!==e.layers[i].backgroundImage))return {status:'insufficient_evidence',reason:'Text suppression changed painted background'};
 // Decode evaluator-generated pixels outside the source page CSP. The source
 // context retains its security policy and no network is permitted here.
 const pixels=await (await getPixelPage()).evaluate(async ({data,rects})=>{
  const img=new Image();img.src='data:image/png;base64,'+data;await img.decode();
  const canvas=document.createElement('canvas');canvas.width=img.width;canvas.height=img.height;const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);
  const colors=new Map();let count=0;
  for(const r of rects){const x=Math.max(0,Math.ceil(r.x)),y=Math.max(0,Math.ceil(r.y)),w=Math.min(img.width-x,Math.floor(r.width)),h=Math.min(img.height-y,Math.floor(r.height));if(w<=0||h<=0)continue;
   const p=ctx.getImageData(x,y,w,h).data;for(let i=0;i<p.length;i+=4){if(p[i+3]!==255)return {error:'Nonopaque painted pixels'};const key=[p[i],p[i+1],p[i+2]].join(',');colors.set(key,(colors.get(key)||0)+1);count++;}
  }
  return {colors:[...colors],count};
 },{data:png.toString('base64'),rects:e.text_rects.map(r=>({...r,x:r.x-clip.viewport_x,y:r.y-clip.viewport_y}))});
 if(pixels.error||!pixels.count)return {status:'insufficient_evidence',reason:pixels.error||'No visible text pixels'};
 const size=parseFloat(e.fontSize),bold=parseInt(e.fontWeight,10)>=700,threshold=size>=24||bold&&size>=18.666666?3:4.5;
 const values=pixels.colors.map(([color,count])=>({color:color.split(',').map(Number),count,ratio:ratio(fg,color.split(',').map(Number))}));
 const minimum=Math.min(...values.map(x=>x.ratio));
 return {status:minimum>=threshold?'passed':'failed',ratio:minimum,threshold,foreground:fg,method:'painted_background_pixels',pixel_count:pixels.count,background_colors:values,background_screenshot:png.toString('base64'),background_screenshot_clip:clip,background_sha256:crypto.createHash('sha256').update(png).digest('hex')};
}
async function collect(page,axe,assets){
 const documentBefore=await page.content(),documentSha=crypto.createHash('sha256').update(documentBefore).digest('hex'),items=[],screenshots={},viewportScreenshots=new Map();
 let pixelContext,pixelPage;
 const getPixelPage=async()=>{
  if(!pixelContext){pixelContext=await page.context().browser().newContext();await pixelContext.route('**/*',r=>r.abort());pixelPage=await pixelContext.newPage();}
  return pixelPage;
 };
 const scrollState=require('./audit_scroll_state');await scrollState.capture(page);let scrollRestoration;
 try{for(const rule of axe.incomplete||[]){if(!['color-contrast','video-caption'].includes(rule.id))continue;
  for(const node of rule.nodes||[]){if(node.target.length!==1||typeof node.target[0]!=='string')continue;
   const selector=node.target[0],loc=page.locator(selector);if(await loc.count()!==1)continue;
   await loc.scrollIntoViewIfNeeded();
   const evidence=await loc.evaluate(el=>{
    const s=getComputedStyle(el),r=el.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(el);
    const rects=[...range.getClientRects()].filter(x=>x.width>0&&x.height>0);
    const layers=[];let paint_complex=false;
    for(let n=el;n;n=n.parentElement){const c=getComputedStyle(n);layers.push({tag:n.tagName,backgroundColor:c.backgroundColor,backgroundImage:c.backgroundImage,opacity:c.opacity,filter:c.filter});
     if(c.backgroundImage!=='none'||c.opacity!=='1'||c.filter!=='none'||c.mixBlendMode!=='normal')paint_complex=true;
     for(const p of ['::before','::after']){const a=getComputedStyle(n,p);if(a.content!=='none'&&a.content!=='normal'&&a.display!=='none'&&(a.backgroundImage!=='none'||!['rgba(0, 0, 0, 0)','transparent'].includes(a.backgroundColor)))paint_complex=true;}
    }
    const samples=rects.flatMap(x=>[.2,.5,.8].map(f=>({x:x.x+x.width*f,y:x.y+x.height/2}))).filter(p=>p.x>=0&&p.x<innerWidth&&p.y>=0&&p.y<innerHeight);
    const stacks=samples.map(p=>{const top=document.elementFromPoint(p.x,p.y);return {...p,top:top?.outerHTML.slice(0,500),occluded:!!top&&top!==el&&!el.contains(top)};});
    return {html:el.outerHTML,text:el.textContent,color:s.color,fontSize:s.fontSize,fontWeight:s.fontWeight,layers,paint_complex,visible:s.display!=='none'&&s.visibility==='visible'&&r.width>0&&r.height>0,occluded:stacks.some(x=>x.occluded),samples:stacks,text_rects:rects.map(x=>({x:x.x,y:x.y,width:x.width,height:x.height})),rect:{x:r.x,y:r.y,width:r.width,height:r.height},currentSrc:el.currentSrc,tracks:el.tagName==='VIDEO'?[...el.querySelectorAll('track')].map(t=>({kind:t.kind,src:t.src,srclang:t.srclang})):undefined};
   });
   if(rule.id==='color-contrast'){evidence.measurement=contrast(evidence);if(evidence.measurement.status==='insufficient_evidence')evidence.measurement=await paintedContrast(page,selector,evidence,getPixelPage);}
   else{const asset=assets.get(evidence.currentSrc);evidence.media=asset?{url:evidence.currentSrc,sha256:asset.sha256,bytes:asset.body.length,...mediaTracks(asset.body)}:{complete:false,error:'Frozen current media resource missing'};}
   const viewport=await page.evaluate(()=>({x:scrollX,y:scrollY,width:innerWidth,height:innerHeight})),key=JSON.stringify(viewport);
   let screenshotId=viewportScreenshots.get(key);
   if(!screenshotId){
    const bytes=await page.screenshot({type:'jpeg',quality:85,caret:'initial'});screenshotId=crypto.createHash('sha256').update(bytes).digest('hex');
    screenshots[screenshotId]={sha256:screenshotId,document_sha256:documentSha,viewport,body:bytes.toString('base64')};viewportScreenshots.set(key,screenshotId);
   }
   evidence.screenshot_id=screenshotId;
   items.push({type:rule.id,target:node.target,evidence});
  }
 }}finally{try{scrollRestoration=await scrollState.restore(page);}finally{if(pixelContext)await pixelContext.close();}}
 const documentAfter=await page.content(),finalSha=crypto.createHash('sha256').update(documentAfter).digest('hex');
 if(finalSha!==documentSha){
  let offset=0;while(offset<Math.min(documentBefore.length,documentAfter.length)&&documentBefore[offset]===documentAfter[offset])offset++;
  const error=Error('Supplement changed frozen document');
  error.document_change={before_sha256:documentSha,after_sha256:finalSha,first_difference_offset:offset,before_context:documentBefore.slice(Math.max(0,offset-120),offset+380),after_context:documentAfter.slice(Math.max(0,offset-120),offset+380)};
  throw error;
 }
 return {version:VERSION,document_sha256:documentSha,viewport:{width:1440,height:1000},scroll_restoration:scrollRestoration,screenshots,items,semantic_observations:await require('./semantic_observations').collect(page)};
}
module.exports={VERSION,mediaTracks,ratio,contrast,collect};
