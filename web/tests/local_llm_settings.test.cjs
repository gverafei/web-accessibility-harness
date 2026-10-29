const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function form({address='', selected='', options, error}={}) {
  function element(extra={}) {
    return Object.assign({listeners:{},disabled:false,textContent:'',
      addEventListener(type,handler){this.listeners[type]=handler;}},extra);
  }
  const server=element({value:address,placeholder:'http://host.docker.internal:11434'});
  const model=element({value:selected,options:options||[{text:'Not configured',value:''}],
    replaceChildren(...items){this.options=items;this.value=items[0]?.value||'';},
    add(option){this.options.push(option);}});
  const refresh=element({dataset:{modelsUrl:'/configuration/ollama-models',
    error:'Connection failed',empty:'No installed models',success:'Verified without generation',
    textLabel:'Text only',visionLabel:'Text and images',unverifiedLabel:'Not verified'}});
  const status=element(); const requests=[];
  const elements={ollama_base_url:server,ollama_model:model,refreshOllamaModels:refresh,
    ollamaModelsStatus:status};
  vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/js/local_llm_settings.js'),'utf8'),{
    document:{getElementById:id=>elements[id]},AbortController,setTimeout,clearTimeout,
    Option:function(text,value){this.text=text;this.value=value;},
    fetch:async (url,request)=>{requests.push({url,...request});
      return {ok:!error,json:async ()=>error ? {error} : {models:[
        {id:'gemma4:latest',name:'gemma4:latest',vision:true,capabilities_verified:true},
        {id:'llama3.2:latest',name:'llama3.2:latest',vision:false,capabilities_verified:true}]}};}
  });
  return {server,model,refresh,status,requests};
}

for (const button of ['refresh']) {
  test(`${button} uses the visibly suggested address when unconfigured`,async()=>{
    const page=form(); await page[button].listeners.click();
    assert.equal(page.server.value,'http://host.docker.internal:11434');
    assert.equal(page.requests.length,1);
    assert.equal(page.requests[0].url,'/configuration/ollama-models');
    assert.equal(JSON.parse(page.requests[0].body).base_url,page.server.value);
    assert.equal(page.model.options.length,3); assert.equal(page.model.value,'');
    assert.equal(page.status.textContent,'Verified without generation');
  });
}
test('clearing the address disables configuration without default auto-probing',async()=>{
  const page=form(); await page.server.listeners.change();
  assert.equal(page.server.value,'');assert.equal(page.requests.length,0);
  assert.equal(page.model.options.length,1);
});
test('an explicit server is preserved and its selected installed model retained',async()=>{
  const page=form({address:'http://research-server:11434',selected:'gemma4:latest'});
  await page.refresh.listeners.click();
  assert.equal(JSON.parse(page.requests[0].body).base_url,'http://research-server:11434');
  assert.equal(page.model.value,'gemma4:latest');assert.equal(page.refresh.disabled,false);
});
test('connection failure remains visible and never initiates generation',async()=>{
  const page=form({error:'Server unavailable'}); await page.refresh.listeners.click();
  assert.equal(page.status.textContent,'Server unavailable');
  assert.equal(page.requests.length,1);assert.equal(page.refresh.disabled,false);
  assert.equal(page.model.options.length,1);
});
