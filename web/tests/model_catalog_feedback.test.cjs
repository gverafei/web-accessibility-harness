const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
test('shared GUI POST helper attaches the server CSRF token',async()=>{let seen;
 const context={document:{addEventListener:()=>{},getElementById:()=>null,querySelector:()=>({content:'fixture-token'}),querySelectorAll:()=>[]},window:{fetch:async(input,init)=>{seen=init;return{ok:true}}},Headers};
 vm.runInNewContext(fs.readFileSync('web/app/static/js/harness.js','utf8'),context);
 await context.window.fetch('/configuration/models',{method:'POST'});assert.equal(seen.headers.get('X-CSRF-Token'),'fixture-token');
});

test('empty prerequisites and unchecked required choices disable submit buttons',()=>{
 const button={disabled:false,hasAttribute:()=>false};
 const workers=[{checked:true}];
 const required={disabled:false,willValidate:true,validity:{valid:false}};
 const handlers={};
 const form={elements:[required],querySelectorAll:selector=>selector.includes('name="workers"')?workers:selector.startsWith('input')?[]:[button],addEventListener:(name,fn)=>handlers[name]=fn};
 const document={addEventListener:()=>{},documentElement:{lang:'es'},getElementById:()=>null,querySelectorAll:selector=>selector.startsWith('form')?[form]:[]};
 const context={document,window:{fetch:async()=>({ok:true})},Headers};
 vm.runInNewContext(fs.readFileSync('web/app/static/js/harness.js','utf8'),context);
 assert.equal(button.disabled,true);
 required.validity.valid=true;handlers.input();assert.equal(button.disabled,false);
 workers[0].checked=false;handlers.change();assert.equal(button.disabled,true);
});
test('decision catalogue needs an enabled default even when native radios are disabled',()=>{
 const button={disabled:false,hasAttribute:()=>false};const radio={checked:false,disabled:true,willValidate:false};
 const handlers={};const form={elements:[radio],querySelectorAll:s=>s==='input[name="default_decision"]'?[radio]:s.startsWith('input')?[]:[button],addEventListener:(name,fn)=>handlers[name]=fn};
 const document={addEventListener:()=>{},getElementById:()=>null,querySelectorAll:s=>s.startsWith('form')?[form]:[]};
 vm.runInNewContext(fs.readFileSync('web/app/static/js/harness.js','utf8'),{document,window:{fetch:async()=>({ok:true})},Headers});
 assert.equal(button.disabled,true);radio.disabled=false;radio.checked=true;handlers.change();assert.equal(button.disabled,false);
});
