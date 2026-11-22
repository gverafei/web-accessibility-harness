'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const VERSION='original-origin-injection-v2';
function readManifest(filename,root='/results') {
 const base=fs.realpathSync(root),file=fs.realpathSync(filename);
 if(!file.startsWith(base+path.sep))throw new Error('Snapshot manifest outside results mount');
 if(fs.statSync(file).size>require('./evidence_limits').MANIFEST_BYTES)throw new Error('Snapshot manifest exceeds limit');
 const p=JSON.parse(fs.readFileSync(file,'utf8')),url=new URL(p.origin);
 if(!['http:','https:'].includes(url.protocol)||url.username||url.password||typeof p.document!=='string'||Buffer.byteLength(p.document)>require('./evidence_limits').DOCUMENT_BYTES||!Array.isArray(p.assets)||p.assets.length>require('./evidence_limits').SNAPSHOT_ASSET_ENTRIES)throw new Error('Invalid origin snapshot manifest');
 if(p.version!==VERSION)throw new Error('Unsupported snapshot transport');
 let total=0;const assets=new Map(),mediaRecords=new Map(),stylesheetVariants=new Map();
 for(const a of p.assets){const u=new URL(a.url);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)throw new Error('Invalid resource URL');const body=Buffer.from(a.body,'base64');total+=body.length;
  if(body.length>require('./evidence_limits').resourceLimit(a.mime)||total>require('./evidence_limits').TOTAL_RESOURCE_BYTES||crypto.createHash('sha256').update(body).digest('hex')!==a.sha256)throw new Error('Invalid frozen resource checksum or size');
  const decoded={...a,body},key=require('./frozen_media').isMedia(a.mime)?require('./frozen_media').transportUrl(u.href):u.href;
  if(require('./frozen_media').isMedia(a.mime)){
   if(assets.has(key)&&assets.get(key).mime!==a.mime)throw Error('Conflicting frozen media type');
   const entries=mediaRecords.get(key)||[];entries.push(decoded);mediaRecords.set(key,entries);
  }else if(assets.has(u.href)&&assets.get(u.href).sha256!==a.sha256)throw new Error('Conflicting frozen resource');
  if(/^text\/css(?:;|$)/i.test(a.mime||'')){
   const variants=stylesheetVariants.get(key)||[];variants.push(decoded);stylesheetVariants.set(key,variants);
  }
  assets.set(key,decoded);
 }
 const derived=(p.mse_buffer_reference?require('./observed_mse_buffers').verifyBundle(p.mse_buffer_reference,url.href):0)+require('./observed_worker_media').verifyBundle(p.worker_media_reference);
 if(total+derived>require('./evidence_limits').TOTAL_RESOURCE_BYTES)throw Error('Combined frozen resource budget exceeded');
 for(const [url,records]of mediaRecords)assets.set(url,require('./frozen_media').assemble(records));
 return {...p,origin:url.href,assets,stylesheetVariants,redirects:require('./frozen_redirects').index(assets),preflights:require('./frozen_cors').index(p.preflights||[],url.href)};
}
async function run(filename,directory,checkOnly=false) {
 fs.mkdirSync(directory,{recursive:true});
 const stage=name=>fs.writeFileSync(path.join(directory,'instrument-stage.json'),JSON.stringify({stage:name,heap_used_bytes:process.memoryUsage().heapUsed,at:Date.now()}));
 stage('manifest'); const p=readManifest(filename);await require('./harness_evidence').publicUrl(p.origin);
 const {chromium}=require('playwright'),launcher=require('chrome-launcher');
 const chrome=await launcher.launch({chromePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',chromeFlags:['--headless','--no-sandbox','--disable-dev-shm-usage']});
 if(process.send)process.send({type:'browser_pid',pid:chrome.pid});
 let browser,puppeteer;
 try {
  browser=await chromium.connectOverCDP('http://127.0.0.1:'+chrome.port);
  const context=await browser.newContext({...require('./desktop_profile').contextOptions(),serviceWorkers:'block'}),page=await context.newPage();
  await require('./media_source_observation').install(page);
  await require('./native_media_pause').install(page);
  const diagnostics={version:VERSION,resource_limit_policy:require('./evidence_limits').VERSION,console_errors:[],script_errors:[],request_failures:[],missing_resources:[],blocked_operations:[],live_network:false,redirect_policy:require('./frozen_redirects').VERSION,ambiguous_redirects:Array.from(p.redirects.ambiguous,([url,variants])=>({url,variants})),blocked_ambiguous_redirects:[]};
  diagnostics.resource_variant_policy=require('./frozen_resource_variants').VERSION;
  diagnostics.resource_variant_choices=[];
  const selectAsset=(url,headers)=>{
   const selected=p.assets.get(url);
   const chosen=require('./frozen_resource_variants').choose(selected,p.stylesheetVariants.get(url),headers);
   if(chosen!==selected&&diagnostics.resource_variant_choices.length<1000){
    diagnostics.resource_variant_choices.push({url,sha256:chosen.sha256,
     selected_sequence:chosen.native_response_sequence??null,default_sequence:selected.native_response_sequence??null});
   }
   return chosen;
  };
  const frozenNetwork=require('./frozen_network').track(page,request=>request.method()==='GET'&&(request.url()===p.origin||p.assets.has(request.url())||p.redirects.has(request.url())));
  page.on('console',m=>{if(m.type()==='error'&&diagnostics.console_errors.length<300)diagnostics.console_errors.push(m.text().slice(0,1000));});
  page.on('pageerror',e=>{if(diagnostics.script_errors.length<300)diagnostics.script_errors.push(e.message.slice(0,1000));});
  page.on('requestfailed',r=>{if(diagnostics.request_failures.length<1000)diagnostics.request_failures.push({url:r.url(),error:r.failure()?.errorText});});
  let initialized=false;
  const fetchSession=await context.newCDPSession(page);
  const mainFrameId=(await fetchSession.send('Page.getFrameTree')).frameTree.frame.id;
  // Playwright route handlers skip the subsequent URLs of a redirect. CDP
  // Fetch pauses every hop, so a frozen redirect cannot escape to live HTTP.
  await fetchSession.send('Fetch.enable',{patterns:[{urlPattern:'http://*',requestStage:'Request'},{urlPattern:'https://*',requestStage:'Request'}]});
  fetchSession.on('Fetch.requestPaused',async event=>{
   const {requestId,request}=event,url=request.url;
   const fail=()=>fetchSession.send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});
   const fulfill=(status,headers,body)=>fetchSession.send('Fetch.fulfillRequest',{requestId,responseCode:status,
    responseHeaders:require('./frozen_headers').entries(headers),body:Buffer.from(body).toString('base64')});
   try{
    if(request.method==='OPTIONS'){
     const reply=p.preflights.lookup(url,request.headers);
     if(reply){await fulfill(reply.status,reply.headers,'');return;}
    }
    if(request.method!=='GET'){diagnostics.blocked_operations.push({url,method:request.method});await fail();return;}
    if(!initialized&&event.resourceType==='Document'&&url===p.origin){initialized=true;await fulfill(200,{'content-type':'text/html; charset=utf-8'},'<!doctype html><html><body></body></html>');return;}
    if(initialized&&event.resourceType==='Document'&&event.frameId===mainFrameId){
     diagnostics.blocked_operations.push({url,method:request.method,kind:'document_navigation'});
     // An aborted main-frame request can commit Chromium's error document,
     // destroying the frozen origin. A 204 denies navigation while preserving
     // the current document; no remote request or replacement body is served.
     await fulfill(204,{},'');return;
    }
    if(p.redirects.ambiguous.has(url)){diagnostics.blocked_ambiguous_redirects.push(url);await fail();return;}
    const redirect=p.redirects.get(url);
    if(redirect){await fulfill(redirect.status,{...redirect.headers,location:redirect.to},'');return;}
    const asset=selectAsset(url,request.headers);
    if(asset){const range=Object.entries(request.headers).find(([key])=>key.toLowerCase()==='range')?.[1];const reply=require('./frozen_media').response(asset,range);await fulfill(reply.status,reply.headers,reply.body);return;}
    if(diagnostics.missing_resources.length<1000)diagnostics.missing_resources.push(url);await fail();
   }catch(error){diagnostics.script_errors.push('Frozen routing: '+error.message);await fail().catch(()=>{});}
  });
  // Additional frame targets are guarded separately; they may use only
  // recorded bodies, never redirected live responses or unknown resources.
  await context.route('**/*',async route=>{
   const req=route.request(),url=req.url();
   if(req.frame()===page.mainFrame())return route.continue();
   if(req.method()==='OPTIONS'){
    const reply=p.preflights.lookup(url,req.headers());
    if(reply)return route.fulfill({status:reply.status,headers:require('./frozen_headers').routeHeaders(reply.headers),body:''});
   }
   if(p.redirects.ambiguous.has(url)){diagnostics.blocked_ambiguous_redirects.push(url);return route.abort();}
   const asset=selectAsset(url,req.headers());
   if(req.method()==='GET'&&asset){const reply=require('./frozen_media').response(asset,req.headers().range);return route.fulfill({status:reply.status,headers:require('./frozen_headers').routeHeaders(reply.headers),body:reply.body});}
   if(req.method()!=='GET')diagnostics.blocked_operations.push({url,method:req.method()});
   else diagnostics.missing_resources.push(url);
   return route.abort();
  });
  await context.routeWebSocket('**/*',socket=>socket.close());
  await require('./measurement_state').install(page);
  await page.goto(p.origin,{waitUntil:'domcontentloaded',timeout:45000});
  await require('./frozen_frame_bridge').install(page, p.assets);
  await require('./native_media_pause').write(page,p.document);
  const helpers=require('./run_axe'),policy=helpers.loadPolicy(p.runtime_config||{});
  stage('frozen_document_initialization');
  diagnostics.document_initialization=await require('./frozen_network').settleDocument(page,frozenNetwork);
  await helpers.activateLazyContent(page,policy);await helpers.settleLazyResources(page,policy);
  // document.write does not reliably emit navigation lifecycle networkidle.
  // Wait on actual registered resource requests, including captured modules.
  // Unknown/ambiguous requests remain blocked and diagnosed, not settlement work.
  stage('frozen_resource_settlement');
  try{diagnostics.resource_settlement=await frozenNetwork.settle();}
  catch(error){fs.writeFileSync(path.join(directory,'resource-settlement.json'),JSON.stringify({...error.settlement,missing_resources:diagnostics.missing_resources,request_failures:diagnostics.request_failures}));throw error;}
  finally{frozenNetwork.dispose();}
  await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(policy.page_settle_delay_ms);
  try {
   diagnostics.frame_initialization = await require('./frozen_frame_bridge').settle(page, p.assets);
  } catch (error) {
   fs.writeFileSync(path.join(directory, 'frame-initialization.json'), JSON.stringify(error.frame_bridge));
   throw error;
  }
  diagnostics.realm=await page.evaluate(()=>({origin:location.origin,base:document.baseURI,secure:isSecureContext,character_set:document.characterSet}));
  if(diagnostics.realm.origin!==new URL(p.origin).origin)throw new Error('Injected page changed origin');
  diagnostics.media_restoration=await require('./frozen_media_state').restore(page,p.media_reference||[],[...p.assets.keys(),...p.redirects.keys()]);
  if(diagnostics.media_restoration.results.some(r=>r.status==='failed')){fs.writeFileSync(path.join(directory,'media-restoration.json'),JSON.stringify({...diagnostics.media_restoration,missing_resources:diagnostics.missing_resources,request_failures:diagnostics.request_failures}));throw Error('Observed frozen media frame restoration failed');}
  diagnostics.mse_restoration=await require('./observed_mse_buffers').restoreReference(page,p.mse_buffer_reference||null,p.origin);
  if(diagnostics.mse_restoration.results.some(r=>['failed','unsupported_codec'].includes(r.status))){fs.writeFileSync(path.join(directory,'mse-restoration.json'),JSON.stringify(diagnostics.mse_restoration));throw Error('Observed MSE frame restoration failed');}
  diagnostics.media_pause=await require('./native_media_pause').snapshot(page);
  diagnostics.worker_media_restoration=await require('./observed_worker_media').restoreReference(page,p.worker_media_reference||null);
  diagnostics.media_state=await require('./frozen_media').settle(page);
  diagnostics.carousel_state=await require('./carousel_measurement').prepare(page);
  fs.mkdirSync(directory,{recursive:true});
  diagnostics.scrollbar_capture_policy=await require('./desktop_capture').prepare(page);
  diagnostics.media_state=await require('./frozen_media').settle(page);
  stage('freeze');
  diagnostics.frozen_frame_bridge = await require('./frozen_frame_bridge').freeze(page);
  diagnostics.measurement_state=await require('./measurement_state').freeze(page);
  diagnostics.frozen_segment_preparation=await require('./desktop_capture').prepare(page);
  // Font/layout and widget preparation can activate an acquired lazy image
  // after the earlier resource wait. Settle that same document before phase 1.
  await helpers.settleLazyResources(page,policy);
  const frozenStability=await helpers.waitForDomStability(page,policy);
  if(!frozenStability.stable)throw new Error('Frozen document did not stabilize before measurement');
  diagnostics.dom_stability=frozenStability;
  diagnostics.frozen_dom_stability=frozenStability;
  diagnostics.animation_restoration=await require('./frozen_animation_state').restore(page,p.animation_reference||[]);
  if(diagnostics.animation_restoration.results.some(r=>r.status==='failed'))throw Error('Observed CSS animation restoration failed');
  diagnostics.native_control_restoration=await require('./native_control_state').restore(page,p.native_control_reference);
  if(diagnostics.native_control_restoration.status==='failed')throw Error('Observed native control state restoration failed');
  stage('visible_evidence');
  const visible=await require('./replay_admission').visibleEvidence(page);
  diagnostics.visible_evidence_policy='stabilized-document-after-segment-preparation-v1';
  if(checkOnly)return {...visible,...diagnostics,blocked_requests:diagnostics.missing_resources};
  stage('phase_before_capture');
  const phaseEvidence=require('./phase_evidence'),phases=[await phaseEvidence.observe(page,'before_capture')];
  const snapshotPath=path.join(directory,'page.html'),screenshotPath=path.join(directory,'page.jpg');
  stage('capture');
  fs.writeFileSync(snapshotPath,await page.content());diagnostics.capture_segments=await require('./desktop_capture').capture(page,screenshotPath);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.waitForTimeout(policy.page_settle_delay_ms);
  stage('phase_after_capture');
  phases.push(await phaseEvidence.observe(page,'after_capture'));
  const standard=Object.hasOwn(helpers.AXE_PROFILES,p.standard)?p.standard:'wcag22aa',tags=[...helpers.AXE_PROFILES[standard],'best-practice'];
  stage('axe');
  const scrollState=require('./audit_scroll_state');await scrollState.capture(page);let raw;
  try{raw=await new (require('@axe-core/playwright').default)({page,axeSource:require('./axe_name_guard').source()}).withTags([...new Set(tags)]).analyze();}
  finally{diagnostics.audit_scroll_restoration=await scrollState.restore(page);}
  // Preserve the completed detector receipt even when supplementary evidence
  // later fails. This partial receipt never makes the full audit admissible.
  fs.writeFileSync(path.join(directory,'axe.json'),JSON.stringify(raw));
  await require('./failure_styles').enrich(page, raw);
  stage('taxonomy_supplement');
  const supplementPath=path.join(directory,'taxonomy-supplement.json');
  try{fs.writeFileSync(supplementPath,JSON.stringify(await require('./taxonomy_supplement').collect(page,raw,p.assets)));}
  catch(error){if(error.document_change)fs.writeFileSync(path.join(directory,'supplement-document-change.json'),JSON.stringify(error.document_change));throw error;}
  stage('phase_after_axe');
  phases.push(await phaseEvidence.observe(page,'after_axe'));
  // Lighthouse's public snapshot API accepts Puppeteer; attach to this exact tab, without navigation.
  puppeteer=await require('puppeteer-core').connect({browserURL:'http://127.0.0.1:'+chrome.port,defaultViewport:null});
  const pages=await puppeteer.pages(),target=pages.find(x=>x.url()===page.url());if(!target)throw new Error('Lighthouse could not attach to injected page');
  stage('lighthouse');
  const lhr=(await require('./axe_name_guard').lighthouse().snapshot(target,{flags:{onlyCategories:['accessibility'],logLevel:'error',
   ...require('./desktop_profile').lighthouseFlags(true)}})).lhr;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.waitForTimeout(policy.page_settle_delay_ms);
  stage('phase_after_lighthouse');
  phases.push(await phaseEvidence.observe(page,'after_lighthouse'));
  diagnostics.phase_evidence=phaseEvidence.summarize(phases);
  const axePath=path.join(directory,'axe.json'),lhPath=path.join(directory,'lighthouse.json');fs.writeFileSync(axePath,JSON.stringify(raw));fs.writeFileSync(lhPath,JSON.stringify(lhr));
  const summary=helpers.summarizeAxeResults(raw,standard,false,tags);
  fs.writeFileSync(path.join(directory,'transport.json'),JSON.stringify({...diagnostics,visible}));
  return {url:p.origin,status:diagnostics.phase_evidence.stable?'completed':'failed',
   error:diagnostics.phase_evidence.stable?undefined:'Instrument document changed between capture and accessibility measurements; source remains recoverable',
   taxonomy_supplement_path:supplementPath,source_snapshot_path:snapshotPath,screenshot_path:screenshotPath,screenshot_mode:'desktop_viewport_segments',axe:{...summary,raw_path:axePath},lighthouse:{accessibility_score:require('./lighthouse_score').extractAccessibilityScore(lhr),raw_path:lhPath},transport:{...diagnostics,visible},wave:{status:'skipped'}};
 }finally{if(puppeteer)puppeteer.disconnect();if(browser)await browser.close().catch(()=>{});await Promise.resolve(chrome.kill()).catch(()=>{});}
}
async function isolated(filename,directory,checkOnly=false){const {runIsolatedNode}=require('./isolated_process');return JSON.parse(await runIsolatedNode([__filename,filename,directory,checkOnly?'check':'audit'],{timeoutMs:180000}));}
if(require.main===module)run(process.argv[2],process.argv[3],process.argv[4]==='check').then(x=>process.stdout.write(JSON.stringify(x))).catch(e=>{process.stderr.write(e.stack);process.exitCode=1;}).finally(()=>{if(process.connected)process.disconnect();});
module.exports={VERSION,readManifest,run,isolated};
