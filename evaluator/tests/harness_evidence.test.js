const test=require('node:test');const assert=require('node:assert/strict');
const {validateDocument,privateAddress,publicUrl,boundedBody}=require('../harness_evidence');
test('independent validator accepts syntax and rejects nested interactive markup',async()=>{
  assert.equal((await validateDocument('<!doctype html><html><head><title>x</title></head><body><main><p>ok</p></main></body></html>')).state,'passed');
  const invalid=await validateDocument('<button><button>x</button></button>');assert.equal(invalid.state,'violated');assert.ok(invalid.errors.length);
});
test('streaming resource bodies cannot indefinitely block a completed capture',async()=>{
 await assert.rejects(boundedBody({body:()=>new Promise(()=>{})},20),/capture timed out/);
 assert.deepEqual(await boundedBody({body:async()=>Buffer.from('captured')},20),Buffer.from('captured'));
});
test('capture blocks local addresses before opening a browser',async()=>{
 assert.equal(privateAddress('127.0.0.1'),true);assert.equal(privateAddress('192.168.1.2'),true);
 await assert.rejects(publicUrl('http://127.0.0.1'));assert.equal(privateAddress('8.8.8.8'),false);
});

test('freezing accepts only the exact stored remediation source route', () => {
  const {frozenSourceUrl}=require('../harness_evidence');
  assert.equal(frozenSourceUrl('http://dataset-server:8080/remediations/12/source-baseline.html'),
    'http://dataset-server:8080/remediations/12/source-baseline.html');
  for (const url of ['http://127.0.0.1/remediations/12/source-baseline.html',
    'http://dataset-server:8080/private', 'http://dataset-server:8080/remediations/12/source-baseline.html?x=1',
    'http://dataset-server:8080/remediations/12/candidate.html']) assert.throws(()=>frozenSourceUrl(url));
});

test('syntax error locations survive line shifts but identify different nested controls', async () => {
 const source='<html><head><title>x</title></head><body><main><a href="/x"><input type="text"></a></main></body></html>';
 const a=await validateDocument(source), b=await validateDocument('\n\n'+source);
 const project=v=>v.errors.map(e=>[e.rule,e.message,e.selector]);
 assert.deepEqual(project(a),project(b));
 assert.ok(a.errors.some(e=>e.selector && e.selector.includes('input')));
 const c=await validateDocument(source.replace('<input type="text">','<button type="button">Save</button>')).catch(e=>{throw e});
 assert.notDeepEqual(project(a),project(c));
});

test('capture failures distinguish browser crashes from publisher rejection',()=>{
 const {captureFailure}=require('../harness_evidence');
 assert.deepEqual(captureFailure(new Error('mouse.move: Target crashed')),
  {error:'mouse.move: Target crashed',failure_kind:'browser_crash',retryable:true});
 assert.equal(captureFailure(new Error('page.goto: Timeout 60000ms exceeded')).failure_kind,'capture_timeout');
 const excluded=captureFailure(new Error('Acquisition excluded: publisher error or verification interstitial.'));
 assert.equal(excluded.failure_kind,'content_rejected');assert.equal(excluded.retryable,false);
 const unknown=captureFailure(new Error('Resource size contract failed'));
 assert.equal(unknown.failure_kind,'capture_error');assert.equal(unknown.retryable,false);
});

test('expanded rendered evidence remains bounded in UTF-8 bytes without truncation',()=>{
 const {checkRenderedEvidence}=require('../harness_evidence');
 assert.equal(checkRenderedEvidence('x'.repeat(2500000)),2500000);
 assert.equal(checkRenderedEvidence('é'.repeat(4000000)),8000000);
 assert.throws(()=>checkRenderedEvidence('é'.repeat(4000001)),/8000002 bytes/);
});
