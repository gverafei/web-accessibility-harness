const test=require('node:test'),assert=require('node:assert/strict');
const {response,complete}=require('../frozen_media');
test('frozen media honors initial, seek, suffix and invalid ranges without live access',()=>{
 const asset={body:Buffer.from('0123456789'),mime:'video/webm',headers:{'access-control-allow-origin':'*'}};
 for(const [range,body,header]of [['bytes=0-3','0123','bytes 0-3/10'],['bytes=6-','6789','bytes 6-9/10'],['bytes=-2','89','bytes 8-9/10']]){
  const r=response(asset,range);assert.equal(r.status,206);assert.equal(r.body.toString(),body);assert.equal(r.headers['content-range'],header);assert.equal(r.headers['access-control-allow-origin'],'*');
 }
 assert.equal(response(asset,'bytes=20-').status,416);assert.equal(response(asset,'bytes=0-1,3-4').status,416);assert.equal(response(asset).body.length,10);
});
test('partial acquisition retains original fragments and appends bounded complete media once',async()=>{
 const fragment={url:'https://example.com/a.webm',mime:'video/webm',body:Buffer.from('34').toString('base64'),http_status:206,sha256:'old',headers:{'content-range':'bytes 3-4/10'}};
 const assets=[fragment],errors=[],visited=[];let requests=0;
 const fetch=async()=>{requests++;return {status:206,headers:{'content-range':'bytes 0-9/10'},body:Buffer.from('0123456789')};};
 await complete(assets,errors,fetch,async u=>visited.push(u));assert.equal(errors.length,0);assert.equal(assets[0],fragment);assert.equal(assets[1].http_status,200);assert.equal(assets[1].media_capture.complete,true);assert.deepEqual(visited,[fragment.url]);
 await complete(assets,errors,fetch,async()=>{});assert.equal(requests,1);
});
test('incomplete or oversized media cannot be presented as a complete frozen resource',async()=>{
 const assets=[{url:'https://example.com/a.webm',mime:'video/webm',body:'eA==',http_status:206}],errors=[];
 await complete(assets,errors,async()=>({status:206,headers:{'content-range':'bytes 1-2/10'},body:Buffer.from('12')}),async()=>{});
 assert.equal(assets.length,2);assert.equal(assets[1].http_status,206);assert.equal(assets[1].media_capture.complete,false);assert.equal(errors[0].kind,'incomplete_media');
});

test('recorded partial ranges keep original offsets and total, deny holes and conflicting overlaps',()=>{
 const {assemble}=require('../frozen_media');
 const part=(start,bytes)=>({url:'https://example.com/a.webm',mime:'video/webm',http_status:206,headers:{'content-range':`bytes ${start}-${start+bytes.length-1}/20`},body:Buffer.from(bytes)});
 const asset=assemble([part(10,'ABCDEFGHIJ'),part(0,'01234'),part(3,'3456')]);
 for(const [range,body,header]of [['bytes=0-','0123456','bytes 0-6/20'],['bytes=12-15','CDEF','bytes 12-15/20'],['bytes=-2','IJ','bytes 18-19/20']]){
  const result=response(asset,range);assert.equal(result.status,206);assert.equal(result.body.toString(),body);assert.equal(result.headers['content-range'],header);
 }
 assert.equal(response(asset,'bytes=7-').status,416);
 assert.equal(response(part(10,'ABCDEFGHIJ')).headers['content-range'],'bytes 10-19/20');
 assert.throws(()=>assemble([part(0,'01234'),part(3,'xx')]),/overlap/);
 assert.throws(()=>assemble([{...part(0,'01234'),headers:{'content-range':'bytes 0-5/20'}}]),/Invalid/);
});
test('bounded recovery keeps an actual prefix for an oversized observed movie, without repeating it',async()=>{
 const assets=[],errors=[],attempted=new Set(),observed=[{url:'https://example.com/large.webm',mime:'video/webm',headers:{}}];let calls=0;
 const fetch=async()=>{calls++;return {status:206,headers:{'content-range':'bytes 0-4/20','content-length':'5'},body:Buffer.from('01234')};};
 for(let i=0;i<3;i++)await complete(assets,errors,fetch,async()=>{},attempted,observed);
 assert.equal(calls,1);assert.equal(assets.length,1);assert.equal(assets[0].media_capture.complete,false);
 assert.equal(assets[0].headers['content-range'],'bytes 0-4/20');assert.equal(assets[0].headers['content-length'],undefined);
});

test('complete media has an explicit eight-megabyte limit with bounded code/CSS and smaller opaque resources',()=>{const {resourceLimit}=require('../evidence_limits');assert.equal(resourceLimit('video/webm'),8000000);assert.equal(resourceLimit('audio/ogg'),8000000);assert.equal(resourceLimit('text/javascript'),16000000);assert.equal(resourceLimit('text/css; charset=utf-8'),16000000);assert.equal(resourceLimit('application/octet-stream'),2000000);});

test('observed loaded video records a genuine complete HLS root and its redirects for declared recovery',async()=>{
 const url='https://example.com/playback',final='https://cdn.example.com/root',body=Buffer.from('#EXTM3U\n#EXTINF:5,\nfirst.ts\n');
 const assets=[],errors=[],visited=[];let reserved=0;
 await complete(assets,errors,async u=>u===url?{status:302,headers:{location:final},body:Buffer.alloc(0)}:{status:200,headers:{'content-type':'application/vnd.apple.mpegurl','access-control-allow-origin':'*'},body},async u=>visited.push(u),new Set(),[{url,mime:'video/unknown',observed_kind:'VIDEO',headers:{}}],n=>reserved+=n);
 assert.equal(errors.length,0);assert.equal(assets.length,1);assert.equal(assets[0].url,final);assert.equal(assets[0].redirect_chain[0].from,url);assert.equal(assets[0].headers['access-control-allow-origin'],'*');assert.equal(reserved,body.length);assert.deepEqual(visited,[url,final]);
 await require('../declared_hls_resources').complete(assets,errors,async u=>{assert.equal(u,'https://cdn.example.com/first.ts');return {status:200,headers:{'content-type':'video/mp2t'},body:Buffer.from('actual-segment')};},async()=>{});
 assert.equal(assets.length,2);assert.equal(errors.length,0);
});
test('observed HLS rejects wrong MIME, false signatures, partial playlists and oversized opaque bodies',async()=>{
 const valid=Buffer.from('#EXTM3U\n#EXTINF:5,\nfirst.ts\n');
 for(const result of [
  {status:200,headers:{'content-type':'text/html'},body:valid},
  {status:200,headers:{'content-type':'application/vnd.apple.mpegurl'},body:Buffer.from('<html>not a playlist</html>')},
  {status:200,headers:{'content-type':'application/vnd.apple.mpegurl'},body:Buffer.from('#EXTM3Ugarbage')},
  {status:206,headers:{'content-type':'application/vnd.apple.mpegurl','content-range':`bytes 0-${valid.length-1}/${valid.length+20}`},body:valid},
  {status:200,headers:{'content-type':'application/vnd.apple.mpegurl'},body:Buffer.concat([valid,Buffer.alloc(2000000)])}
 ]){
  const assets=[],errors=[];let reserved=0;
  await complete(assets,errors,async()=>result,async()=>{},new Set(),[{url:'https://example.com/playback',mime:'video/unknown',observed_kind:'VIDEO'}],n=>reserved+=n);
  assert.equal(assets.length,0);assert.equal(errors.length,1);assert.equal(reserved,0);
 }
});
test('a complete ranged HLS response retains its bytes without retaining a misleading partial header',async()=>{
 const body=Buffer.from('#EXTM3U\r\n#EXT-X-ENDLIST\r\n'),assets=[],errors=[];
 await complete(assets,errors,async()=>({status:206,headers:{'content-type':'audio/x-mpegurl; charset=utf-8','content-range':`bytes 0-${body.length-1}/${body.length}`},body}),async()=>{},new Set(),[{url:'https://example.com/playback',mime:'video/unknown',observed_kind:'VIDEO'}]);
 assert.equal(errors.length,0);assert.equal(assets[0].http_status,200);assert.equal(assets[0].headers['content-range'],undefined);assert.equal(Buffer.from(assets[0].body,'base64').toString(),body.toString());
});
test('native selected-only recovery keeps unrelated segment fragments and spends no bytes completing them',async()=>{
 const fragment={url:'https://cdn.example.com/old-segment',mime:'video/mp2t',http_status:206,headers:{'content-range':'bytes 0-2/10000000'},body:Buffer.from('abc').toString('base64')};
 const assets=[fragment],errors=[],calls=[];let reserved=0;const selected='https://cdn.example.com/selected-playlist';
 await complete(assets,errors,async url=>{calls.push(url);return {status:200,headers:{'content-type':'application/vnd.apple.mpegurl'},body:Buffer.from('#EXTM3U\n#EXT-X-ENDLIST\n')};},async()=>{},new Set(),[{url:selected,mime:'video/unknown',observed_kind:'VIDEO'}],n=>reserved+=n,true);
 assert.deepEqual(calls,[selected]);assert.equal(assets[0],fragment);assert.equal(assets.length,2);assert.equal(errors.length,0);assert.equal(reserved,Buffer.from(assets[1].body,'base64').length);
 const emptyAssets=[fragment];await complete(emptyAssets,[],async()=>assert.fail('MSE segment is already frozen'),async()=>{},new Set(),[],()=>assert.fail('No completion reservation'),true);assert.deepEqual(emptyAssets,[fragment]);
});
test('an already captured native redirect alias is not downloaded again as a different playlist',async()=>{
 const original={url:'https://cdn.example.com/native-signed/root',mime:'application/vnd.apple.mpegurl',http_status:200,body:Buffer.from('#EXTM3U\n#EXT-X-ENDLIST\n').toString('base64'),redirect_chain:[{from:'https://example.com/current-source',to:'https://cdn.example.com/native-signed/root',status:302}]};
 const assets=[original],errors=[];
 await complete(assets,errors,async()=>assert.fail('Do not replace an already frozen native root'),async()=>{},new Set(),[{url:'https://example.com/current-source',mime:'video/unknown',observed_kind:'VIDEO'}],()=>assert.fail('No duplicate reservation'),true);
 assert.deepEqual(assets,[original]);assert.deepEqual(errors,[]);
});

test('selected media fragments are HTTP keys while original requested identity is recorded',async()=>{
 const media=require('../frozen_media'),url='https://media.example/video.webm',body=Buffer.from('original');let requested=[];
 const result=await media.complete([],[],async u=>{requested.push(u);return{status:200,headers:{'content-type':'video/webm'},body};},async()=>{},new Set(),[{url:url+'#t=0.1',mime:'video/unknown',observed_kind:'VIDEO'}],()=>{},true);
 assert.deepEqual(requested,[url]);assert.equal(result.assets[0].url,url);assert.equal(result.assets[0].media_capture.requested_url,url+'#t=0.1');
 requested=[];await media.complete(result.assets,[],async u=>{requested.push(u);},async()=>{},new Set(),[{url:url+'#t=1',mime:'video/unknown',observed_kind:'VIDEO'}],()=>{},true);assert.deepEqual(requested,[]);
});
