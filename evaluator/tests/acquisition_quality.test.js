const test = require('node:test');
const assert = require('node:assert/strict');
const {validateQualityPolicy, pageRejection, evidenceRejection} = require('../acquisition_quality');
const strict = {require_complete_evidence: true, exclude_explicit_content: true};
test('missing response never becomes a fabricated successful release bundle', () => {
  assert.match(evidenceRejection({html:'<html></html>',screenshot_path:'/tmp/page.jpg'},strict),/response body/);
  assert.equal(evidenceRejection({html:'<html></html>',response_html:'<html></html>',screenshot_path:'/tmp/page.jpg'},strict),null);
});
test('optional evidence remains supported outside strict dataset acquisitions', () => {
  assert.equal(evidenceRejection({},{}),null);
});
test('verification and HTTP errors are not home-page measurements', () => {
  for (const title of ['Bot Verification','403 - Forbidden: Access is denied.','Challenge Validation','Access to this page has been denied','HTTP Status 429 – Too Many Requests']) {
    assert.ok(pageRejection({url:'https://example.org',title},{}));
  }
  assert.ok(pageRejection({url:'https://example.org',httpStatus:503},{}));
});
test('legitimate sparse/login/accessibility education pages remain eligible', () => {
  for (const title of ['Login','Internet Speed Test','Security research: accessible captcha','Best scooter for Adults & Kids']) {
    assert.equal(pageRejection({url:'https://example.org',title},strict),null);
  }
});
test('explicit scope exclusions are opt-in, not a global product ban', () => {
  const item={url:'https://adultfriendfinder.com',title:'AdultFriendFinder'};
  assert.ok(pageRejection(item,strict)); assert.equal(pageRejection(item,{}),null);
  assert.ok(pageRejection({url:'https://sci-hub.mx'},{excluded_hosts:['sci-hub.mx']}));
});
test('policy cannot expand into arbitrary parameters or invalid hosts', () => {
  assert.throws(()=>validateQualityPolicy({excluded_hosts:['https://example.org/']}));
  assert.throws(()=>validateQualityPolicy({require_complete_evidence:'false'}));
  assert.throws(()=>validateQualityPolicy({secret:true}));
});
test('explicit content in non-English titles is excluded only under dataset policy', () => {
  for (const title of ['Nonton Bokep Indo','Phim Sex Vietsub HD','エロ漫画','最新成人大片免费播放','Скачать эротические игры','أفضل الاباحية الفيديو']) {
    const item={url:'https://example.org',title};
    assert.ok(pageRejection(item,strict));
    assert.equal(pageRejection(item,{}),null);
  }
});
