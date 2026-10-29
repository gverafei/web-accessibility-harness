const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const code=fs.readFileSync(__dirname+'/../app/static/js/remediation_live_motion.js','utf8');
function fixture(event){
 let glows=0,replaced;
 const classes={add(){}};
 const actor=id=>({dataset:{actorKey:'Decisions|luna',liveActor:id,actorCalls:'2'},innerHTML:'calls',classList:classes,closest:()=>({dataset:{liveStage:'taxonomy'}}),animate(){glows++;},replaceWith(node){replaced=node;}});
 const oldActor=actor('1'),newActor=actor(event);
 const old={dataset:{activeNode:'taxonomy',flowRevision:'1'},querySelector:()=>null,querySelectorAll:()=>[oldActor]};
 const next={dataset:{activeNode:'taxonomy',flowRevision:event},matches:()=>true,classList:classes,querySelector:()=>null,querySelectorAll:s=>s==='[data-actor-key]'?[newActor]:[]};
 const window={matchMedia:()=>({matches:false}),addEventListener(){}};
 vm.runInNewContext(code,{window,document:{querySelectorAll:()=>[]}});window.prepareLiveMotion({querySelector:()=>old},next);
 return {oldActor,replaced,glows};
}
test('repeated actor invocation keeps its DOM identity and glows once',()=>{const f=fixture('2');assert.equal(f.replaced,f.oldActor);assert.equal(f.glows,1);assert.equal(f.oldActor.dataset.liveActor,'2');});
test('unchanged actor does not blink or glow on unrelated refresh',()=>{const f=fixture('1');assert.equal(f.replaced,f.oldActor);assert.equal(f.glows,0);});

function routeFixture(){const window={addEventListener(){}};vm.runInNewContext(code,{window,document:{querySelectorAll:()=>[]}});return window.liveStageRoute;}
test('a skipped stage uses a visible outside lane matching the packet route',()=>{
 const route=routeFixture(),nodes={context:{x:125,y:100,rx:70,ry:60},evidence:{x:375,y:100,rx:70,ry:60},selection:{x:625,y:100,rx:70,ry:60},repair:{x:875,y:100,rx:70,ry:60},retain:{x:125,y:314,rx:70,ry:60}};
 assert.equal(route(nodes,'context','evidence'),'M195 100H305');
 assert.equal(route(nodes,'evidence','repair'),'M445 100H463V10H787V100H805');
 assert.equal(route(nodes,'retain','evidence'),'M195 314H213V10H287V100H305');
 assert.equal(route(nodes,'repair','repair'),null);
});

test('repeated layout alignment keeps one connector and the same packet route',()=>{
 const children=[],packet={style:{}};
 const make=()=>({attrs:{},setAttribute(k,v){this.attrs[k]=v;},append(){},remove(){children.splice(children.indexOf(this),1);}});
 const paths=Array.from({length:7},make);
 const svg={getBoundingClientRect:()=>({left:0,top:0,width:1000,height:400}),querySelectorAll:s=>s==='.live-revisit,.live-revisit-label'?children.filter(n=>/^live-revisit/.test(n.attrs.class)):paths,querySelector:s=>s==='.live-event-packet'?packet:null,append(n){children.push(n);}};
 const keys=['context','evidence','selection','repair','audit','taxonomy','preserve','retain'];
 const nodes=keys.map((key,i)=>({dataset:{liveStage:key},getBoundingClientRect:()=>({left:50+(i%4)*250,top:i<4?40:260,width:120,height:120})}));
 const panel={dataset:{previousStage:'evidence',activeNode:'repair',eventKind:'generate',transitionLabel:'Direct transition'},querySelector:s=>s==='.live-loop-links'?svg:{textContent:'stage'},querySelectorAll:()=>nodes};
 const document={querySelectorAll:()=>[panel],createElementNS:make},window={addEventListener(){}};
 vm.runInNewContext(code,{window,document});window.alignLiveMotion();
 assert.equal(children.filter(n=>n.attrs.class==='live-revisit').length,1);
 assert.equal(children.filter(n=>n.attrs.class==='live-revisit-label').length,0);
 assert.equal(packet.style.offsetPath,`path("${children.find(n=>n.attrs.class==='live-revisit').attrs.d}")`);
});

// Regression: reverse travel on connected stages must reuse their physical edge.
test('adjacent reverse travel follows the existing straight connection',()=>{
 const route=routeFixture(),nodes={context:{x:125,y:100,rx:70,ry:60},evidence:{x:375,y:100,rx:70,ry:60},repair:{x:875,y:100,rx:70,ry:60},audit:{x:875,y:314,rx:70,ry:60}};
 assert.equal(route(nodes,'evidence','context'),'M305 100H195');
 assert.equal(route(nodes,'audit','repair'),'M875 254V160');
});
test('reverse alignment highlights one existing edge and creates no extra line',()=>{
 const children=[],packet={style:{}};
 const make=()=>({attrs:{},setAttribute(k,v){this.attrs[k]=v;},append(){},remove(){children.splice(children.indexOf(this),1);}});
 const paths=Array.from({length:7},make);
 const svg={getBoundingClientRect:()=>({left:0,top:0,width:1000,height:400}),querySelectorAll:s=>s==='.live-revisit,.live-revisit-label'?children.filter(n=>/^live-revisit/.test(n.attrs.class)):paths,querySelector:s=>s==='.live-event-packet'?packet:null,append(n){children.push(n);}};
 const keys=['context','evidence','selection','repair','audit','taxonomy','preserve','retain'];
 const nodes=keys.map((key,i)=>({dataset:{liveStage:key},getBoundingClientRect:()=>({left:50+(i%4)*250,top:i<4?40:260,width:120,height:120})}));
 const panel={dataset:{previousStage:'evidence',activeNode:'context',eventKind:'generate'},querySelector:s=>s==='.live-loop-links'?svg:{textContent:'stage'},querySelectorAll:()=>nodes};
 const document={querySelectorAll:()=>[panel],createElementNS:make},window={addEventListener(){}};
 vm.runInNewContext(code,{window,document});window.alignLiveMotion();
 assert.equal(children.length,0);
 assert.equal(paths.filter(p=>p.attrs['data-transfer-active']==='true').length,1);
 assert.equal(paths[0].attrs['data-transfer-active'],'true');
 assert.equal(packet.style.offsetPath,'path("M286 100H184")');
});
