const {chromium} = require('playwright');

function documentEvidence(mode) {
    const root=document.scrollingElement||document.documentElement;
    const htmlStyle=getComputedStyle(document.documentElement),body=document.body;
    // CSS Overflow: BODY overflow propagated to the viewport has used value
    // visible on BODY. Its (possibly zero-height) box must not clip descendants.
    const bodyStyle=body&&getComputedStyle(body);
    const viewportOverflowBody=body&&document.documentElement.tagName==='HTML'&&
      htmlStyle.overflowX==='visible'&&htmlStyle.overflowY==='visible'&&
      htmlStyle.contain==='none'&&bodyStyle.contain==='none'&&bodyStyle.display!=='none';
    const canScrollX=root.scrollWidth>root.clientWidth+1,canScrollY=root.scrollHeight>root.clientHeight+1;
    const visible = e => {
      const r=e.getBoundingClientRect();if(!r.width || !r.height)return false;
      let top=r.top,bottom=r.bottom,left=r.left,right=r.right;
      for(let node=e;node;node=node.parentElement){
        const s=getComputedStyle(node);if(s.display==='none' || s.visibility==='hidden' || Number(s.opacity)===0)return false;
        if(node===e||node===root||(viewportOverflowBody&&node===body))continue;
        const box=node.getBoundingClientRect();
        if(!canScrollY&&['auto','scroll','hidden','clip'].includes(s.overflowY)){
          if(s.overflowY!=='clip'){top-=Math.max(0,node.scrollHeight-node.clientHeight-node.scrollTop);bottom+=node.scrollTop;}
          top=Math.max(top,box.top+node.clientTop);bottom=Math.min(bottom,box.top+node.clientTop+node.clientHeight);
          if(bottom<=top)return false;
        }
        if(!canScrollX&&['auto','scroll','hidden','clip'].includes(s.overflowX)){
          if(s.overflowX!=='clip'){left-=Math.max(0,node.scrollWidth-node.clientWidth-node.scrollLeft);right+=node.scrollLeft;}
          left=Math.max(left,box.left+node.clientLeft);right=Math.min(right,box.left+node.clientLeft+node.clientWidth);
          if(right<=left)return false;
        }
      }
      return (canScrollY||(bottom>0&&top<innerHeight))&&(canScrollX||(right>0&&left<innerWidth));
    };
    const noncontentPixel=e=>{
      const box=e.getBoundingClientRect();
      // Use the actual rendered dimensions. A CSS-sized tracking pixel is
      // equivalent to an attribute-sized pixel, but a stretched 1px image or
      // an image used as a control must still be checked for decoded content.
      return e.getAttribute('alt')==='' && box.width>0 && box.width<=1 &&
        box.height>0 && box.height<=1 &&
        !['title','aria-label','aria-labelledby','role','tabindex','onclick'].some(a=>e.hasAttribute(a)) &&
        !e.closest('a[href],button,[role="button"]');
    };
    const images=[...document.images].filter(e=>visible(e) && !noncontentPixel(e));
    if(mode==='image_urls')return images.map(e=>e.currentSrc||e.src).filter(Boolean);
    const texts=[];if(document.body){const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;while((node=walker.nextNode())){const parent=node.parentElement;if(parent && !parent.closest('script,style,noscript') && visible(parent))texts.push(node.textContent);}}
    const text=texts.join(' ').replace(/\s+/g,' ').trim();
    const controlLabel=e=>{const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),parts=[];let node;while((node=walker.nextNode()))if(!node.parentElement.closest('script,style,noscript')&&visible(node.parentElement))parts.push(node.textContent);return parts.join(' ').replace(/\s+/g,' ').trim().slice(0,160);};
    const controls=[...document.querySelectorAll('a[href],button,input,select,textarea,summary,[role="button"]')].filter(visible).map(e =>
      [e.tagName,e.getAttribute('type') || '',controlLabel(e) || e.getAttribute('placeholder') || e.getAttribute('name') || ''].join('|')).sort();
    const media=[...document.querySelectorAll('video,audio')].filter(visible);
    const mediaStates=media.map(e=>{
      const durable=url=>{try{const u=new URL(url,location.href);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}};
      const sources=[...new Set([e.getAttribute('src')&&durable(e.getAttribute('src')),...[...e.querySelectorAll('source[src]')].map(s=>durable(s.getAttribute('src')))].filter(Boolean))].sort();
      const mediaSource=window[Symbol.for('a11yharness.mediaSourceObservation')]?.(e.currentSrc||e.src)||null;
      const deferred=e.preload==='none'&&!e.autoplay&&e.paused&&e.readyState===0&&[0,1].includes(e.networkState)&&!e.error&&sources.length>0;
      const unbuffered=e.preload==='none'&&!e.autoplay&&e.paused&&e.readyState===0&&e.networkState===2&&!e.error&&sources.length>0&&mediaSource?.ready_state==='open'&&mediaSource.buffers===0;
      const path=[];for(let n=e;n&&n!==document.documentElement;n=n.parentElement){const peers=[...n.parentElement.children].filter(p=>p.tagName===n.tagName);path.unshift(n.tagName.toLowerCase()+':nth-of-type('+(peers.indexOf(n)+1)+')');}
      let objectKind=null;try{objectKind=e.srcObject?.constructor?.name||null;}catch{objectKind='unobservable';}
      const buffered=[];for(let i=0;i<Math.min(32,e.buffered.length);i++)buffered.push([e.buffered.start(i),e.buffered.end(i)]);
      const metadata=objectKind==='MediaSourceHandle'&&e.paused&&e.readyState===1&&e.currentTime===0&&!e.error&&buffered.length===0&&e.videoWidth>0&&e.videoHeight>0;
      return {media_object_observation_version:'observed-media-object-v1',src_object_kind:objectKind,buffered_ranges:buffered,video_width:e.videoWidth||0,video_height:e.videoHeight||0,position_version:'observed-media-position-v1',position_path:'html > '+path.join(' > '),src_attribute:e.getAttribute('src'),source_attributes:[...e.querySelectorAll('source[src]')].map(s=>s.getAttribute('src')),current_time:e.currentTime,paused:e.paused,current_src:e.currentSrc,media_source:mediaSource,identity:{kind:e.tagName,preload:e.preload,poster:e.poster||'',sources},state:metadata?'metadata':deferred?'deferred':unbuffered?'unbuffered':e.error||e.readyState<2?'broken':'loaded',ready_state:e.readyState,network_state:e.networkState,error:e.error?.code||null};
    });
    const dimensions=e=>{if(!e)return null;const s=getComputedStyle(e);return {client_height:e.clientHeight,scroll_height:e.scrollHeight,overflow_y:s.overflowY,position:s.position};};
    return {visibility_version:'reachable-document-regions-v2',image_exclusion_version:'explicit-empty-alt-rendered-pixel-v2',document_scroll_range:{x:canScrollX,y:canScrollY},text,controls,control_label_version:'visible-text-nodes-v1',visible_images:images.length,broken_images:images.filter(e=>!e.complete || !e.naturalWidth).length,
      broken_image_urls:images.filter(e=>!e.complete || !e.naturalWidth).map(e=>e.currentSrc||e.src),
      visible_media:media.length,broken_media:mediaStates.filter(e=>e.state==='broken').length,deferred_media:mediaStates.filter(e=>e.state==='deferred').length,unbuffered_media:mediaStates.filter(e=>e.state==='unbuffered').length,media_descriptors:mediaStates,metadata_media:mediaStates.filter(e=>e.state==='metadata').length,media_evidence_version:'observed-media-state-v4',document_scrolling:{html:dimensions(document.documentElement),body:dimensions(document.body)},
      node_count:document.querySelectorAll('*').length,title:document.title,viewport:{width:innerWidth,height:innerHeight}};
}

async function visibleEvidence(page) {
 const evidence=await page.evaluate(documentEvidence);
 return {...evidence,native_control_reference:await require('./native_control_state').capture(page)};
}
async function visibleImageUrls(page) {return page.evaluate(documentEvidence,'image_urls');}

async function replayCheck(value) {
  const url=new URL(value);
  if(url.protocol!=='http:' || url.hostname!=='dataset-server' || url.port!=='8080' || !url.pathname.startsWith('/harness/')) throw new Error('Replay admission requires a frozen local snapshot');
  const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  try {
    const context=await browser.newContext({...require('./desktop_profile').contextOptions(),serviceWorkers:'block'});
    const blocked=[];
    await context.route('**/*',async route => {
      const u=new URL(route.request().url());
      if(u.hostname==='dataset-server' && u.port==='8080' && u.pathname.startsWith('/harness/')) await route.continue();
      else {blocked.push(route.request().url());await route.abort();}
    });
    const page=await context.newPage();await require('./media_source_observation').install(page);const errors=[];
    page.on('pageerror',e=>errors.push(e.message.slice(0,500)));
    await page.goto(url.href,{waitUntil:'domcontentloaded',timeout:45000});
    const {activateLazyContent,settleLazyResources,waitForDomStability,loadPolicy}=require('./run_axe');
    const policy=loadPolicy();
    await activateLazyContent(page,policy);await settleLazyResources(page,policy);await waitForDomStability(page,policy);
    await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(1000);
    return {...await visibleEvidence(page),script_errors:errors,blocked_requests:[...new Set(blocked)]};
  } finally {await browser.close();}
}
module.exports={visibleEvidence,visibleImageUrls,replayCheck};
