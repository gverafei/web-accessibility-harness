const test=require('node:test'),assert=require('node:assert/strict');
const {index,capture}=require('../frozen_redirects');
test('recorded redirects preserve status and security headers without live requests',async()=>{
 const first={redirectedFrom:()=>null,url:()=> 'https://example.com/old.css',method:()=> 'GET',response:async()=>({status:()=>301,headers:()=>({'access-control-allow-origin':'*','set-cookie':'private'})})};
 const final={redirectedFrom:()=>first,url:()=> 'https://cdn.example.com/new.css'};
 const chain=await capture(final);assert.equal(chain[0].status,301);assert.deepEqual(chain[0].headers,{'access-control-allow-origin':'*'});
 assert.equal(index(new Map([['final',{url:final.url(),redirect_chain:chain}]])).get(first.url()).to,final.url());
});
test('unsafe, cyclic and inconsistent redirect evidence is rejected',()=>{
 const asset={url:'https://example.com/final',redirect_chain:[{from:'https://example.com/old',to:'https://example.com/final',status:302}]};
 for(const change of [{to:'file:///private'},{to:'https://example.com/old'},{to:'https://example.com/other'},{status:200}]){
  assert.throws(()=>index(new Map([['a',{...asset,redirect_chain:[{...asset.redirect_chain[0],...change}]}]])));
 }
 const result=index(new Map([['https://example.com/old',{url:'https://example.com/old',sha256:'recorded-body',mime:'image/gif',http_status:200}],['final',asset]]));
 assert.equal(result.has('https://example.com/old'),false);
 assert.equal(result.ambiguous.get('https://example.com/old').length,2);
 assert.equal(result.ambiguous.get('https://example.com/old')[0].kind,'resource_body');
});

test('ambiguous redirects retain all variants and never select a destination',()=>{
 const source='https://example.com/tracker',targets=['https://a.example/end','https://b.example/end','https://c.example/end'];
 const assets=new Map(targets.map(url=>[url,{url,redirect_chain:[{from:source,to:url,status:302,headers:{}}]}]));
 const result=index(assets);assert.equal(result.has(source),false);assert.equal(result.ambiguous.get(source).length,3);
 const reversed=index(new Map([...assets].reverse()));assert.equal(reversed.has(source),false);assert.deepEqual(new Set(reversed.ambiguous.get(source).map(r=>r.to)),new Set(targets));
});
test('identical recorded resource retains its distinct native aliases with each original permission',()=>{
 const url='https://cdn.example.com/master',asset={url,redirect_chain:[],additional_redirect_chains:[[{from:'https://example.com/first',to:url,status:302,headers:{'access-control-allow-origin':'https://example.com'}}],[{from:'https://example.com/second',to:url,status:307,headers:{}}]]};
 const result=index(new Map([[url,asset]]));assert.equal(result.get('https://example.com/first').status,302);assert.equal(result.get('https://example.com/second').status,307);assert.equal(result.ambiguous.size,0);assert.equal(result.get('https://example.com/first').headers['access-control-allow-origin'],'https://example.com');
 for(const extra of [null,{},Array(65).fill([]),[[{from:'https://example.com/third',to:'file:///private',status:302}]],[[{from:'https://example.com/third',to:'https://cdn.example.com/wrong',status:302}]]]){
  if(extra===null)continue;assert.throws(()=>index(new Map([[url,{...asset,additional_redirect_chains:extra}]])));
 }
 const conflicting={...asset,additional_redirect_chains:[...asset.additional_redirect_chains,[{from:'https://example.com/first',to:url,status:302,headers:{'access-control-allow-origin':'*'}}]]};
 const denied=index(new Map([[url,conflicting]]));assert.equal(denied.has('https://example.com/first'),false);assert.equal(denied.ambiguous.size,1);
});
