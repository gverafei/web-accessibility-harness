const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const dns = require('node:dns/promises');
const net = require('node:net');
const {chromium} = require('playwright');

function privateAddress(ip) {
  return ip === '::1' || ip.startsWith('fc') || ip.startsWith('fd') || ip.startsWith('fe80:') ||
    ip.startsWith('::ffff:') || /^(0|10|127|169\.254|192\.168)\./.test(ip) || /^172\.(1[6-9]|2\d|3[01])\./.test(ip);
}
async function publicUrl(value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid acquisition URL');
  const host = url.hostname.replace(/^\[|\]$/g, '');
  const addresses = net.isIP(host) ? [{address:host}] : await dns.lookup(host, {all:true});
  if (!addresses.length || addresses.some(a => privateAddress(a.address))) throw new Error('Acquisition requires a public address');
  return url.href;
}
async function boundedBody(response, timeoutMs=15000) {
  let timer;
  try {
    return await Promise.race([response.body(), new Promise((_,reject) => {
      timer=setTimeout(() => reject(new Error('Resource body capture timed out')),timeoutMs);
    })]);
  } finally {clearTimeout(timer);}
}
function frozenSourceUrl(value) {
  const url = new URL(value);
  if (url.origin !== 'http://dataset-server:8080' || !/^\/remediations\/\d+\/source-baseline\.html$/.test(url.pathname) || url.search || url.hash || url.username || url.password)
    throw new Error('Freeze requires a stored remediation source');
  return url.href;
}
function checkRenderedEvidence(document) {
  const bytes=Buffer.byteLength(document);
  if(bytes>require('./evidence_limits').DOCUMENT_BYTES)throw new Error('Rendered DOM exceeds the bounded document capture evidence limit ('+bytes+' bytes)');
  return bytes;
}
async function capture(url, root, frozen=false, injection=null) {
  if (injection) { await publicUrl(injection.origin); if(typeof injection.document!=='string' || Buffer.byteLength(injection.document)>require('./evidence_limits').DOCUMENT_BYTES) throw new Error('Invalid injection document'); url=injection.origin; }
  else if (frozen) frozenSourceUrl(url); else await publicUrl(url);
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless:true,
    args:['--no-sandbox', '--disable-dev-shm-usage']});
  const directory = path.join(root, 'harness_' + crypto.randomUUID());
  fs.mkdirSync(directory, {recursive:true});
  const assets = [], errors = [], tasks = []; let bytes = 0;
  try {
    const context = await browser.newContext({...require('./desktop_profile').contextOptions(), serviceWorkers:'block'});
    let page,initialized=false;
    await context.route('**/*', async route => {
      try {
        const request=route.request(),requested=request.url();
        if(request.method()!=='GET'){errors.push({url:requested,reason:'write operation blocked'});return route.abort();}
        if(injection && !initialized && request.isNavigationRequest() && request.frame()===page.mainFrame() && requested===new URL(url).href){initialized=true;return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><body></body></html>'});}
        if (!(frozen && requested===url)) await publicUrl(requested);
        await route.continue();
      }
      catch { errors.push({url:route.request().url(), reason:'non-public address blocked'}); await route.abort(); }
    });
    page = await context.newPage();
  await require('./media_source_observation').install(page);
  await require('./native_media_pause').install(page);
    const {activateLazyContent,settleLazyResources,waitForDomStability,loadPolicy}=require('./run_axe');
    const policy=loadPolicy();
    const networkSession=await context.newCDPSession(page);
    await networkSession.send('Network.enable',{maxTotalBufferSize:200*1024*1024,maxResourceBufferSize:100*1024*1024});
    let finalDocument=null;
    const hardTimeout=setTimeout(() => browser.close().catch(() => {}),policy.axe_hard_timeout_ms);
    const clearHardTimeout=() => clearTimeout(hardTimeout);
    browser.on('disconnected',clearHardTimeout);
    page.on('response', response => {
      if(response.request().isNavigationRequest() && response.request().frame()===page.mainFrame()) finalDocument=response;
      if (tasks.length >= 1000) { if(errors.length<1000)errors.push({url:response.url(),reason:'resource response count limit'}); return; }
      tasks.push((async () => {
        const request = response.request();
        if (request.method() !== 'GET' || response.status() >= 400 || (response.status() >= 300 && response.status() < 400)) return;
        const length = Number(response.headers()['content-length'] || 0);
        const resourceLimit=require('./evidence_limits').resourceLimit(response.headers()['content-type']);
        if (length > resourceLimit || bytes > require('./evidence_limits').TOTAL_RESOURCE_BYTES) { errors.push({url:response.url(),reason:'resource capture budget'}); return; }
        try {
          const body = await boundedBody(response);
          if (body.length > resourceLimit || bytes + body.length > require('./evidence_limits').TOTAL_RESOURCE_BYTES) { errors.push({url:response.url(),reason:'resource capture budget'}); return; }
          bytes += body.length;
          assets.push({url:response.url(), http_status:response.status(), mime:response.headers()['content-type'] || 'application/octet-stream',
            redirect_chain:await require('./frozen_redirects').capture(request),
            headers:Object.fromEntries(Object.entries(response.headers()).filter(([key])=>['access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy','content-range','accept-ranges'].includes(key))),
            body:body.toString('base64'), sha256:crypto.createHash('sha256').update(body).digest('hex')});
        } catch { errors.push({url:response.url(),reason:'body unavailable'}); }
      })());
    });
    const response = await page.goto(url, {waitUntil:'domcontentloaded', timeout:policy.page_load_timeout_ms});
    if(injection) await require('./native_media_pause').write(page,injection.document);
    const initialNetwork=injection ? Buffer.from(injection.document) : await boundedBody(response).catch(() => null);
    await page.waitForLoadState('networkidle', {timeout:policy.network_idle_timeout_ms}).catch(() => {});
    await activateLazyContent(page,policy);await settleLazyResources(page,policy);const stability=await waitForDomStability(page,policy);
    await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(policy.page_settle_delay_ms);
    const visible=await require('./replay_admission').visibleEvidence(page);
    const rendered = await page.content();
    const title=await page.title();
    const {pageRejection}=require('./acquisition_quality');
    const rejected=pageRejection({url:page.url(),title,body:await page.locator('body').innerText().catch(()=>''),httpStatus:response?.status() || 0},{exclude_explicit_content:true});
    if (rejected) throw new Error(rejected);
    checkRenderedEvidence(rendered);
    const documentResponse=finalDocument || response;
    const networkBody=documentResponse===response && initialNetwork ? initialNetwork : await boundedBody(documentResponse).catch(() => null);
    const network=networkBody ? networkBody.toString('utf8') : '';
    const scrollbar_capture_policy=await require('./desktop_capture').prepare(page);
    await require('./desktop_capture').capture(page,path.join(directory,'page.jpg'));
    await Promise.allSettled(tasks);
    const evidence = {media_pause:await require('./native_media_pause').snapshot(page),scrollbar_capture_policy,schema:'a11yharness/1', requested_url:url, captured_url:page.url(), http_status:documentResponse?.status(), title, network, rendered, assets, errors, visible, stability,
      capture_limits:{version:require('./evidence_limits').VERSION,image_bytes:8000000,media_bytes:8000000,injected_document_bytes:require('./evidence_limits').DOCUMENT_BYTES,rendered_dom_bytes:require('./evidence_limits').DOCUMENT_BYTES,resource_bytes:2000000,total_resource_bytes:require('./evidence_limits').TOTAL_RESOURCE_BYTES,resource_responses:1000},
      scope:'Frozen captured resources and observable DOM. Server-side actions and unacquired interactions are not verified.',
      node_version:process.version, chromium_version:browser.version(), viewport:{width:1440,height:1000}, screenshot_mode:'full_page'};
    fs.writeFileSync(path.join(directory,'capture.json'), JSON.stringify(evidence));
    return {capture_path:path.join(directory,'capture.json'), screenshot_path:path.join(directory,'page.jpg')};
  } finally { await browser.close(); }
}
function captureFailure(error) {
  const message=String(error?.message || error);
  const failure_kind=/Target crashed|page crashed|browser.*(?:closed|crash)/i.test(message) ? 'browser_crash' :
    /timeout|timed out/i.test(message) ? 'capture_timeout' :
    /(?:^|Axe: )Acquisition (?:excluded:|blocked by)/.test(message) ? 'content_rejected' : 'capture_error';
  return {error:message, failure_kind, retryable:['browser_crash','capture_timeout'].includes(failure_kind)};
}
async function validateDocument(document) {
  if (typeof document !== 'string' || Buffer.byteLength(document) > require('./evidence_limits').DOCUMENT_BYTES) throw new Error('Document size exceeds validation contract');
  const {HtmlValidate} = require('html-validate');
  const validator = new HtmlValidate({rules:{'close-order':'error','no-dup-attr':'error','no-dup-id':'error',
    'element-permitted-content':'error','element-permitted-parent':'error','element-permitted-occurrences':'error','void-content':'error'}});
  const report = await validator.validateString(document);
  return {state:report.valid ? 'passed':'violated', validator:'html-validate', version:require('html-validate/package.json').version,
    errors:report.results.flatMap(r => r.messages).map(m => ({rule:m.ruleId,line:m.line,column:m.column,message:m.message,selector:m.selector,context:m.context}))};
}
module.exports = {checkRenderedEvidence, capture, captureFailure, validateDocument, publicUrl, privateAddress, boundedBody, frozenSourceUrl};
