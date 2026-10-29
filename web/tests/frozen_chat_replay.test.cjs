const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
 const inside={text:'patched chat',contains:()=>false,matches:()=>false,nodeType:1};
 const roots=[{contains:n=>n===inside,setAttribute(){},matches:()=>true,nodeType:1},{contains:()=>false,setAttribute(){},matches:()=>true,nodeType:1}];
 const outside={text:'article',contains:()=>false,matches:()=>false,nodeType:1};
 const body={text:'body',contains:()=>true,matches:()=>false,nodeType:1};
 function $(values){if(!Array.isArray(values))values=[values];const c=Object.create($.fn);c.values=values;c.length=values.length;c.jquery='fixture';return c;}
 $.parseHTML=text=>[{text,nodeType:1,matches:()=>text==='duplicate SDK root'}];
 $.fn={filter(fn){return $(this.values.filter((n,i)=>fn(i,n)));},toArray(){return this.values;},
  append(...args){this.values.forEach(n=>n.text+=(args.flatMap(a=>a?.jquery?a.toArray():[a])).map(a=>a.text||a).join(''));return this;},
  prepend(...args){return this.append(...args);},on(){this.values.forEach(n=>n.bound=true);return this;},
  html(value){if(value===undefined)return this.values[0].text;this.values.forEach(n=>n.text=value);return this;}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/frozen_chat_replay.js'),'utf8'),{window:{jQuery:$},document:{querySelectorAll:()=>roots,addEventListener(){}}});
 return {$,roots,inside,outside,body};
}
test('repeated SDK construction preserves patched controls and still binds handlers',()=>{
 const {$,inside,body}=fixture();$(inside).append('duplicated button').prepend('duplicated wrapper').on('click',()=>{});
 $(body).append('duplicate SDK root');assert.equal(inside.text,'patched chat');assert.equal(inside.bound,true);assert.equal(body.text,'body');
});
test('unrelated inserts, mixed selections and interactive iframe replacement remain available',()=>{
 const {$,inside,outside,body}=fixture();const mixed=$([inside,outside]);assert.equal(mixed.append('new article'),mixed);
 assert.equal(inside.text,'patched chat');assert.equal(outside.text,'articlenew article');
 $(body).append('ordinary new region');assert.equal(body.text,'bodyordinary new region');
 $(inside).html('<iframe title="Chat session"></iframe>');assert.match(inside.text,/Chat session/);
});
