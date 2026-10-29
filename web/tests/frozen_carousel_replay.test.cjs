const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function fixture() {
  const counts = {initializations:0};
  const inside = {text:'original'};
  const root = {text:'captured', contains:n=>n === inside,
    getAttribute:()=>JSON.stringify({initialSlide:1,slidesToShow:1}),
    setAttribute(key,value){this[key]=value;}};
  const outside = {text:'unrelated', contains:()=>false};
  function $(items) {
    const values = Array.isArray(items) ? items : [items];
    const collection = Object.create($.fn);
    collection.values=values;collection.length=values.length;collection.jquery='fixture';
    return collection;
  }
  $.fn = {
    toArray(){return this.values;},
    filter(fn){return $(this.values.filter((n,i)=>fn(i,n)));},
    each(fn){this.values.forEach((n,i)=>fn(i,n));return this;},
    html(...args){if(!args.length)return this.values[0]?.text;this.values.forEach(n=>n.text=args[0]);return this;},
    text(...args){return this.html(...args);},
    empty(){this.values.forEach(n=>n.text='');return this;},
    append(value){this.values.forEach(n=>n.text+=value);return this;},
    slick(options){
      if(typeof options==='string')return options==='getSlick'?this.values[0].slick:this;
      counts.initializations++;
      this.values[0].slick={refresh(){this.buildOut();$(root).html('responsive');},buildOut(){$(inside).html('plugin');}};
      $(this.values[0]).empty().append('plugin-built');
      return this;
    }
  };
  const context=vm.createContext({document:{readyState:'complete',querySelectorAll:()=>[root],addEventListener(){}},window:{jQuery:$,addEventListener(){}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/frozen_carousel_replay.js'),'utf8'),context);
  return {$,root,inside,outside,counts};
}

test('captured carousel initializes once, with plugin writes allowed and feed writes blocked',()=>{
  const {$,root,counts}=fixture();
  assert.equal(counts.initializations,1);
  assert.equal(root.text,'plugin-built');
  assert.equal(root['data-warp-replay-status'],'initialized');
  $(root).empty().append('feed clone').html('feed replacement');
  $(root).slick({autoplay:true});$(root).slick({autoplay:false});
  assert.equal(root.text,'plugin-built');assert.equal(counts.initializations,1);
  assert.equal($(root).html(),'plugin-built');
});

test('unrelated and mixed selections keep ordinary jQuery writes and return values',()=>{
  const {$,root,outside}=fixture();
  $(outside).html('editable');assert.equal(outside.text,'editable');
  const both=$([root,outside]);assert.equal(both.empty().append('extra'),both);
  assert.equal(root.text,'plugin-built');assert.equal(outside.text,'extra');
  assert.equal($(root).slick('getSlick'),root.slick);
});

test('responsive plugin rebuilds keep nested scoped permissions',()=>{
  const {$,root,inside}=fixture();
  root.slick.refresh();
  assert.equal(root.text,'responsive');assert.equal(inside.text,'plugin');
  $(inside).html('feed');$(root).html('feed');
  assert.equal(root.text,'responsive');assert.equal(inside.text,'plugin');
});
