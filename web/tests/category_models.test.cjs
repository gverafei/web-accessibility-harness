const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

async function page({cloudEnabled=true,localError=false,job={}}={}) {
  const select={options:[],value:'',disabled:true,listeners:{},
    addEventListener(k,v){this.listeners[k]=v;},add(o){this.options.push(o);},
    replaceChildren(...items){this.options=items;}};
  const start={disabled:true,dataset:{missingCount:'8'}}; const status={}; const requests=[];
  const config={modelsUrl:'/urls/category-models',chooseModel:'Choose',defaultLabel:'Default',
    localLabel:'local, no cloud cost',cloudLabel:'cloud, API cost',keyRequired:'Key required',
    localModelsError:'Local unavailable',noModels:'No models'};
  const elements={managedUrlConfig:{textContent:JSON.stringify(config)},categoryModel:select,
    startCategorization:start,categoryModelsStatus:status,categoryAutomation:{dataset:{job:JSON.stringify(job)}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/js/category_models.js'),'utf8'),{
    document:{getElementById:id=>elements[id]},Option:function(text,value){this.text=text;this.value=value;},
    fetch:async(url,options)=>{requests.push({url,...options});return{ok:true,json:async()=>({
      local_error:localError,models:[
        {id:'ollama/gemma',label:'gemma',provider:'local',enabled:true},
        {id:'anthropic/example@high',label:'Example',provider:'cloud',enabled:cloudEnabled,is_default:true}]
    })};}
  });
  await new Promise(resolve=>setImmediate(resolve));
  return {select,start,status,requests};
}
test('configured local and cloud default appear, selection never starts generation',async()=>{
  const p=await page();assert.equal(p.select.options.length,3);
  assert.equal(p.select.value,'anthropic/example@high');assert.equal(p.start.disabled,false);
  p.select.value='ollama/gemma';p.select.listeners.change();
  assert.equal(p.start.disabled,false);assert.match(p.select.title,/no cloud cost/);
  assert.equal(p.requests.length,1);assert.equal(p.requests[0].method,undefined);
});
test('missing key requires explicit local selection without fallback',async()=>{
  const p=await page({cloudEnabled:false});assert.equal(p.select.value,'');
  assert.equal(p.start.disabled,true);assert.equal(p.select.disabled,false);
  assert.equal(p.select.options[2].disabled,true);
});
test('local discovery errors remain visible',async()=>{
  const p=await page({localError:true});assert.equal(p.status.textContent,'Local unavailable');
});
test('running job retains its frozen choice, not the new default',async()=>{
  const p=await page({job:{status:'running',model:'ollama/old',model_config_json:'{"choice_id":"ollama/old"}'}});
  assert.equal(p.select.value,'ollama/old');assert.equal(p.select.disabled,true);
  assert.equal(p.start.disabled,true);
});
