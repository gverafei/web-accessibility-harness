const {test} = require('node:test');
const assert = require('node:assert/strict');
const {init} = require('../app/static/js/ui_feedback.js');

class Node {
  constructor(tag='button') {
    this.tagName=tag.toUpperCase();this.attrs=new Map();this.dataset={};this.style={minWidth:''};
    this.children=[];this.textContent='Generate report';this.hidden=false;this.parent=null;
    if(tag==='button') {this.disabled=false;this.type='submit';}
    const names=new Set();
    this.classList={add:(...items)=>items.forEach(x=>names.add(x)),remove:(...items)=>items.forEach(x=>names.delete(x)),contains:x=>names.has(x)};
  }
  getAttribute(name){return this.attrs.get(name)??null;}
  setAttribute(name,value){this.attrs.set(name,String(value));}
  removeAttribute(name){this.attrs.delete(name);}
  hasAttribute(name){return this.attrs.has(name);}
  querySelectorAll(){return this.children.filter(x=>x.tagName==='SVG');}
  getBoundingClientRect(){return {width:160};}
  append(...items){items.forEach(item=>{item.parent=this;this.children.push(item);});}
  prepend(item){item.parent=this;this.children.unshift(item);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}
  replaceChildren(...items){this.children=[];this.append(...items);}
  closest(){return this.tagName==='A'?this:null;}
  focus(){this.focused=true;}
  scrollIntoView(){this.scrolled=true;}
}
function fixture() {
  const events={},windowEvents={},timers=new Map(),polls=new Map(),cookies=new Map(),frames=[],submissions=[],elements={appNotifications:new Node('div'),uiFeedbackLabels:{textContent:JSON.stringify({loading:'Loading…',export:'Preparing export…',close:'Close'})}};
  const document={getElementById:id=>elements[id]||null,createElement:tag=>new Node(tag),addEventListener:(type,callback)=>events[type]=callback};
  let sequence=0;
  Object.defineProperty(document,'cookie',{get:()=>[...cookies].map(([key,value])=>`${key}=${value}`).join('; '),set:value=>{const [pair]=value.split(';'),[key,val]=pair.split('=');if(value.includes('Max-Age=0'))cookies.delete(key);else cookies.set(key,val);}});
  const env={document,location:new URL('http://localhost/acquisition/new'),addEventListener:(type,callback)=>windowEvents[type]=callback,
    crypto:{getRandomValues:array=>array.fill(++sequence)},
    setInterval:(fn,delay)=>{const id=polls.size+1;polls.set(id,{fn,delay});return id;},clearInterval:id=>polls.delete(id),
    requestAnimationFrame:fn=>frames.push(fn), HTMLFormElement:{prototype:{submit(){submissions.push(this);}}},
    setTimeout:(fn,delay)=>{const id=timers.size+1;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
  return {api:init(env),events,windowEvents,timers,polls,cookies,elements,frames,submissions,env};
}
function event(target,more={}) {return {target,button:0,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...more};}
function form(control) {const f=new Node('form');f.method='post';f.elements=[control];f.checkValidity=()=>true;return f;}

test('shared spinner preserves label, icon, dimensions, attributes and prior disabled state',()=>{
  const {api}=fixture(),button=new Node(),icon=new Node('svg');button.append(icon);
  button.setAttribute('aria-label','Create evaluation');button.style.minWidth='4rem';
  const done=api.busy(button);
  assert.equal(button.disabled,true);assert.equal(button.getAttribute('aria-busy'),'true');
  assert.equal(icon.hidden,true);assert.match(button.children[0].className,/spinner-border-sm/);
  assert.equal(button.textContent,'Generate report');assert.equal(button.style.minWidth,'160px');
  assert.equal(api.busy(button),done);assert.equal(button.children.length,2);
  done();done();assert.equal(button.disabled,false);assert.equal(icon.hidden,false);
  assert.equal(button.getAttribute('aria-label'),'Create evaluation');assert.equal(button.getAttribute('aria-busy'),null);
  assert.equal(button.style.minWidth,'4rem');assert.equal(button.children.length,1);
  button.disabled=true;api.busy(button)();assert.equal(button.disabled,true);
});
test('native and keyboard submissions preserve named action and block a duplicate POST',()=>{
  const {events,windowEvents}=fixture(),button=new Node();button.name='action';button.value='pause';
  const f=form(button);events.submit(event(f,{submitter:button}));
  assert.equal(button.disabled,true);assert.equal(f.children[0].name,'action');assert.equal(f.children[0].value,'pause');
  const second=event(f);events.submit(second);assert.equal(second.defaultPrevented,true);
  windowEvents.pageshow();assert.equal(button.disabled,false);assert.equal(f.children.length,0);
  events.submit(event(f));assert.equal(button.disabled,true);
});
test('external form controls and explicit requestSubmit buttons are supported',()=>{
  const {events,elements}=fixture(),button=new Node(),f=form(button);f.elements=[];
  events.submit(event(f,{submitter:button}));assert.equal(button.disabled,true);
  const other=new Node(),f2=form(other);f2.elements=[];f2.dataset.busyControl='add';elements.add=other;
  events.submit(event(f2));assert.equal(other.disabled,true);
});
test('acquisition POST waits for a painted spinner, preserves action and cannot repeat',()=>{
  const {events,frames,submissions,env}=fixture(),button=new Node(),f=form(button);
  f.setAttribute('data-busy-navigation','');f.setAttribute('action','/run');
  button.name='action';button.value='generate';button.setAttribute('formaction','/custom');
  const first=event(f,{submitter:button});events.submit(first);
  assert.equal(first.defaultPrevented,true);assert.equal(button.getAttribute('aria-busy'),'true');
  assert.equal(submissions.length,0);assert.equal(f.children[0].value,'generate');
  const duplicate=event(f,{submitter:button});events.submit(duplicate);assert.equal(duplicate.defaultPrevented,true);
  frames.shift()();assert.equal(submissions.length,0); // allow a paint between frames
  env.HTMLFormElement.prototype.submit=function(){assert.equal(this.getAttribute('action'),'/custom');submissions.push(this);};
  frames.shift()();assert.equal(submissions.length,1);assert.equal(f.getAttribute('action'),'/run');
});
test('reset before delayed navigation cancels the POST; submission errors restore control',()=>{
  for (const fails of [false,true]) {
    const {events,frames,windowEvents,submissions,env}=fixture(),button=new Node(),f=form(button);
    f.setAttribute('data-busy-navigation','');button.name='action';button.value='generate';
    events.submit(event(f,{submitter:button}));frames.shift()();
    if (fails) {
      env.HTMLFormElement.prototype.submit=()=>{throw new Error('Navigation failed');};
      assert.throws(()=>frames.shift()(),/Navigation failed/);
    } else {windowEvents.pageshow();frames.shift()();}
    assert.equal(submissions.length,0);assert.equal(button.disabled,false);assert.equal(f.children.length,0);
  }
});
test('invalid, prevented, dialog and new-tab submissions never start loading',()=>{
  for(const kind of ['invalid','prevented','dialog','blank','optout']) {
    const {events}=fixture(),button=new Node(),f=form(button),e=event(f,{submitter:button});
    if(kind==='invalid')f.checkValidity=()=>false;
    if(kind==='prevented')e.defaultPrevented=true;
    if(kind==='dialog')f.method='dialog';if(kind==='blank')f.target='_blank';if(kind==='optout')f.dataset.busy='off';
    events.submit(e);assert.equal(button.disabled,false,kind);
  }
});
test('download submissions use bounded recovery and retain hidden selection fields',()=>{
  const {events,timers}=fixture(),button=new Node(),f=form(button),field=new Node('input');
  field.name='run_ids';field.value='806';f.append(field);f.setAttribute('data-busy-download','');
  events.submit(event(f,{submitter:button}));assert.equal(button.disabled,true);
  assert.equal([...timers.values()][0].delay,45000);[...timers.values()][0].fn();
  assert.equal(button.disabled,false);assert.equal(f.children[0].value,'806');
});
test('button links load during same-window navigation and downloads, without intercepting their destination',()=>{
  const {events,windowEvents,timers}=fixture(),link=new Node('a');link.setAttribute('href','/experiments/131');
  const click=event(link);events.click(click);assert.equal(click.defaultPrevented,false);
  assert.equal(link.getAttribute('aria-busy'),'true');assert.equal(timers.size,0);
  const repeat=event(link);events.click(repeat);assert.equal(repeat.defaultPrevented,true);
  windowEvents.pageshow();assert.equal(link.getAttribute('aria-busy'),null);
  link.setAttribute('download','');events.click(event(link));assert.equal(timers.size,1);
  [...timers.values()][0].fn();assert.equal(link.getAttribute('aria-busy'),null);
});
test('download readiness stops spinner immediately and restores href, without waiting for focus',()=>{
  const {events,polls,cookies,timers}=fixture(),link=new Node('a');
  link.setAttribute('download','');link.setAttribute('href','/raw/axe?existing=1');events.click(event(link));
  const url=new URL(link.getAttribute('href')),token=url.searchParams.get('_download_token');
  assert.match(token,/^[a-f0-9]{32}$/);assert.equal(url.searchParams.get('existing'),'1');
  assert.equal([...polls.values()][0].delay,100);assert.equal(link.getAttribute('aria-busy'),'true');
  cookies.set(`warp_download_${token}`,'ready');[...polls.values()][0].fn();
  assert.equal(link.getAttribute('aria-busy'),null);assert.equal(link.getAttribute('href'),'/raw/axe?existing=1');
  assert.equal(cookies.size,0);assert.equal(polls.size,0);assert.equal(timers.size,0);
});
test('batch export keeps selection fields and removes tracking token on error response',()=>{
  const {events,polls,cookies}=fixture(),button=new Node(),f=form(button),field=new Node('input');
  f.setAttribute('data-busy-download','');field.name='run_ids';field.value='806';f.append(field);
  events.submit(event(f,{submitter:button}));
  const tokenField=f.children.find(child=>child.name==='_download_token');
  cookies.set(`warp_download_${tokenField.value}`,'error');[...polls.values()][0].fn();
  assert.equal(button.disabled,false);assert.deepEqual(f.children,[field]);assert.equal(cookies.size,0);
  events.submit(event(f,{submitter:button}));assert.equal(button.disabled,true);
});
test('two concurrent downloads finish independently and pageshow clears watchers',()=>{
  const {events,polls,cookies,windowEvents}=fixture(),links=[new Node('a'),new Node('a')];
  links.forEach((link,index)=>{link.setAttribute('download','');link.setAttribute('href',`/raw/${index}`);events.click(event(link));});
  const tokens=links.map(link=>new URL(link.getAttribute('href')).searchParams.get('_download_token'));
  assert.notEqual(tokens[0],tokens[1]);cookies.set(`warp_download_${tokens[0]}`,'ready');
  [...polls.values()].forEach(poll=>poll.fn());
  assert.equal(links[0].getAttribute('aria-busy'),null);assert.equal(links[1].getAttribute('aria-busy'),'true');
  windowEvents.pageshow();assert.equal(polls.size,0);assert.equal(links[1].getAttribute('href'),'/raw/1');
});
test('local controls, external URLs, new tabs, modified clicks and canceled navigation are excluded',()=>{
  for(const kind of ['hash','samehash','external','blank','modifier','middle','prevented','toggle','disabled']) {
    const {events}=fixture(),link=new Node('a'),e=event(link);link.setAttribute('href','/experiments/1');
    if(kind==='hash')link.setAttribute('href','#panel');if(kind==='samehash')link.setAttribute('href','/acquisition/new#panel');
    if(kind==='external')link.setAttribute('href','https://example.org');if(kind==='blank')link.target='_blank';
    if(kind==='modifier')e.ctrlKey=true;if(kind==='middle')e.button=1;if(kind==='prevented')e.defaultPrevented=true;
    if(kind==='toggle')link.setAttribute('data-bs-toggle','collapse');if(kind==='disabled')link.classList.add('disabled');
    events.click(e);assert.equal(link.getAttribute('aria-busy'),null,kind);
  }
});
test('save outcomes use top flash styling and text-only rendering, not executable HTML',()=>{
  const {api,elements}=fixture();api.notify('<img src=x onerror=alert(1)>','success');
  const alert=elements.appNotifications.children[0];assert.match(alert.className,/alert-success alert-dismissible fade show/);
  assert.equal(alert.children[0].textContent,'<img src=x onerror=alert(1)>');assert.equal(alert.children[1].getAttribute('aria-label'),'Close');
  assert.equal(alert.getAttribute('role'),'status');assert.equal(alert.scrolled,true);assert.equal(alert.focused,true);
  api.notify('Save failed','danger');assert.equal(elements.appNotifications.children.length,1);
  assert.equal(elements.appNotifications.children[0].getAttribute('role'),'alert');
});
