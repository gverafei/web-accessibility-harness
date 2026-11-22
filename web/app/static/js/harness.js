'use strict';
document.getElementById('harnessTheme')?.addEventListener('click',async()=>{const root=document.documentElement,themes=['light','dark','system'];const next=themes[(themes.indexOf(root.dataset.themeChoice)+1)%3];const response=await fetch('/theme/'+next,{headers:{Accept:'application/json'}});if(response.ok){root.dataset.themeChoice=next;root.dataset.theme=next==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):next;}});
// Administrative POSTs use the same server-issued token as native forms.
const originalFetch=window.fetch.bind(window);window.fetch=(input,init={})=>{if(String(init.method||'GET').toUpperCase()==='POST'){init.headers=new Headers(init.headers||{});init.headers.set('X-CSRF-Token',document.querySelector('meta[name="csrf-token"]').content);}return originalFetch(input,init);};
window.warpAlert=async text=>{const box=document.createElement('div');box.className='alert alert-info';box.setAttribute('role','status');box.textContent=text;document.getElementById('appNotifications').append(box);};
window.warpNotify=(text,kind='info')=>{const box=document.createElement('div');box.className='alert alert-'+kind;box.setAttribute('role','status');box.textContent=text;document.getElementById('appNotifications').append(box);};
window.warpButtonBusy=button=>{button.disabled=true;button.setAttribute('aria-busy','true');return()=>{button.disabled=false;button.removeAttribute('aria-busy');};};

// The server validates every submission; these guards expose unavailable actions.
(() => {
  const campaign=document.getElementById('campaignForm');
  let pairedEdited=false;
  campaign?.elements.namedItem('conditions_json').addEventListener('input',()=>pairedEdited=true);
  function visible(group,show) {
    group.hidden=!show;
    group.querySelectorAll('input,select,textarea').forEach(control=>{
      if(control.dataset.originalDisabled===undefined)control.dataset.originalDisabled=String(control.disabled);
      control.disabled=!show||control.dataset.originalDisabled==='true';
    });
  }
  function updateCampaign() {
    if(!campaign)return;
    const named=name=>campaign.elements.namedItem(name);
    campaign.querySelectorAll('[data-source]').forEach(group=>visible(group,group.dataset.source===named('source_kind').value));
    named('urls').required=named('source_kind').value==='urls';
    named('page_ids').required=named('source_kind').value==='snapshots';
    named('list_id').required=named('source_kind').value==='tranco';
    named('count').readOnly=!['tranco','curated'].includes(named('source_kind').value);
    if(named('source_kind').value==='urls')named('count').value=named('urls').value.split(/\r?\n/).filter(line=>line.trim()).length;
    if(named('source_kind').value==='snapshots')named('count').value=named('page_ids').selectedOptions.length;
    named('reserve_count').disabled=named('source_kind').value!=='tranco';
    named('reserve_count').closest('label').hidden=named('source_kind').value!=='tranco';
    const mode=named('mode').value,partition=named('partition');
    for(const option of partition.options)option.disabled=mode==='frozen'?option.value==='longitudinal':option.value!==mode;
    if(partition.selectedOptions[0].disabled)partition.value=mode==='frozen'?'development':mode;
    const selector=named('selector').value;
    campaign.querySelectorAll('[data-selector]').forEach(group=>visible(group,group.dataset.selector===selector));
    named('orchestrator').required=selector==='structured';
    const usesDecision=[selector,named('retriever').value].includes('decisions');
    campaign.querySelectorAll('[data-decision-role]').forEach(group=>visible(group,usesDecision));
    named('decision_model').required=usesDecision;
    named('policy_id').required=(mode==='frozen'&&selector==='linucb');
    if((mode==='frozen'&&selector==='linucb')){
      const button=campaign.querySelector('button[type="submit"]');
      button.toggleAttribute('data-policy-missing',!named('policy_id').value);
    }else campaign.querySelector('button[type="submit"]').removeAttribute('data-policy-missing');
    const explicit=named('use_explicit_conditions').checked;
    for(const name of ['conditions_json','contrasts_json'])named(name).disabled=!explicit;
    const workers=[...campaign.querySelectorAll('input[name="workers"]:checked')];
    if(!pairedEdited&&workers.length){
      const paired=JSON.parse(named('conditions_json').value);
      paired.forEach(condition=>{condition.worker_id=workers[0].value;if(condition.level===6)condition.selector=selector;});
      named('conditions_json').value=JSON.stringify(paired,null,2);
    }

  }
  const forms=[...document.querySelectorAll('form[data-guarded],form[method="post"]')];
  function guard(form) {
    let valid=[...form.elements].every(control=>control.disabled||!control.willValidate||control.validity.valid);
    for(const name of ['workers','levels']) {
      const checks=[...form.querySelectorAll(`input[type="checkbox"][name="${name}"]`)];
      if(checks.length&&!checks.some(control=>control.checked))valid=false;
    }
    const decisions=[...form.querySelectorAll('input[name="default_decision"]')];
    if(decisions.length&&!decisions.some(radio=>radio.checked&&!radio.disabled))valid=false;
    form.querySelectorAll('button:not([type="button"]),input[type="submit"]').forEach(button=>button.disabled=button.hasAttribute('data-unavailable')||button.hasAttribute('data-policy-missing')||!valid);
  }
  function update() {
    document.querySelectorAll('input[name="default_decision"]').forEach(radio=>{
      const enabled=[...document.querySelectorAll('input[name="enabled_decisions"]')].find(toggle=>toggle.value===radio.value);
      radio.disabled=!enabled?.checked;if(radio.disabled)radio.checked=false;
    });
    updateCampaign();forms.forEach(guard);
  }
  forms.forEach(form=>{form.addEventListener('input',update);form.addEventListener('change',update);});
  update();

  // Older evidence forms share the same caption geometry as campaign fields.
  document.querySelectorAll('.harness-grid label:not(.check-label)').forEach(label=>{
    if(label.querySelector('.field-label'))return;
    const control=label.querySelector('input:not([type="checkbox"]):not([type="radio"]),select,textarea');
    if(!control)return;
    const caption=document.createElement('span');caption.className='field-label';
    while(label.firstChild&&label.firstChild!==control)caption.append(label.firstChild);
    label.classList.add('harness-field');label.prepend(caption);
  });
})();

// A bounded preview opens the unchanged frozen image; Escape/native dialog closes it.
document.addEventListener('click',event=>{
  const link=event.target.closest('[data-capture]');if(!link)return;
  const viewer=document.getElementById('captureViewer');
  if(!viewer?.showModal)return;
  event.preventDefault();const img=viewer.querySelector('img');
  img.src=link.href;img.alt=link.querySelector('img').alt;viewer.showModal();
});

// Same delete interaction on every record list: confirmation, then submit.
document.addEventListener('submit',async event=>{
  const form=event.target;if(!form.matches('form[data-confirm-delete]'))return;
  if(form.dataset.confirmed==='true')return;
  event.preventDefault();
  const dialog=document.getElementById('deleteConfirmation'),message=dialog.querySelector('[data-delete-message]');
  const campaign=form.dataset.confirmDelete==='campaign',es=document.documentElement.lang==='es';
  message.textContent=campaign?(es?'¿Borrar esta campaña y sus corridas?':'Delete this campaign and its runs?'):(es?'¿Borrar esta corrida?':'Delete this run?');
  const accepted=await new Promise(resolve=>{
    const onClose=()=>{dialog.removeEventListener('close',onClose);resolve(dialog.returnValue==='delete');};
    dialog.returnValue='';dialog.addEventListener('close',onClose);dialog.showModal();
  });
  if(accepted){form.dataset.confirmed='true';form.requestSubmit();}
});
