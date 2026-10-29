const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
test('main document fallback retains the original navigation bytes and ignores subresources',async()=>{
 const session=new EventEmitter(),calls=[];
 session.send=async(method,args)=>{calls.push({method,args});return {base64Encoded:true,body:Buffer.from('<html>Response, not hydrated DOM</html>').toString('base64')};};
 const reader=require('../main_document_response').collect(session);
 session.emit('Network.responseReceived',{type:'Script',requestId:'script',response:{url:'https://example.test/script'}});
 session.emit('Network.responseReceived',{type:'Document',requestId:'doc',response:{url:'https://example.test/'}});
 session.emit('Network.loadingFinished',{requestId:'script'});
 session.emit('Network.loadingFinished',{requestId:'doc'});
 assert.equal(await reader.read('https://example.test/'),'<html>Response, not hydrated DOM</html>');
 assert.deepEqual(calls,[{method:'Network.getResponseBody',args:{requestId:'doc'}}]);
 assert.equal(await reader.read('https://example.test/missing'),null);
});
test('unavailable original body remains unavailable instead of substituting DOM or another fetch',async()=>{
 const session=new EventEmitter();session.send=async()=>{throw Error('evicted');};
 const reader=require('../main_document_response').collect(session);
 session.emit('Network.responseReceived',{type:'Document',requestId:'doc',response:{url:'https://example.test/'}});
 session.emit('Network.loadingFinished',{requestId:'doc'});
 assert.equal(await reader.read('https://example.test/'),null);
});
