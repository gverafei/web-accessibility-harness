const test=require('node:test'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
test('installed fallback fonts cover Japanese Chinese and Korean acquisition text',()=>{
 for(const language of ['ja','zh-cn','zh-tw','ko']){
  const family=execFileSync('fc-match',['-f','%{family}',':lang='+language],{encoding:'utf8'});
  assert.match(family,/CJK/,'Missing CJK fallback for '+language);
 }
});
