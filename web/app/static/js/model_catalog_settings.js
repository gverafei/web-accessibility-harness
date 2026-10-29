/* Catalogue editing never mutates a recorded experiment or invokes a model. */
(() => {
  const root = document.getElementById('modelCatalogEditor');
  if (!root) return;
  const endpoint = root.dataset.endpoint, rows = document.getElementById('modelCatalogRows');
  const decisions = root.dataset.kind === 'decisions';
  const status = document.getElementById('modelCatalogStatus'), picker = document.getElementById('modelProviderPicker');
  const search = document.getElementById('providerModelSearch'), results = document.getElementById('providerModelResults');
  const providerStatus = document.getElementById('providerModelStatus');
  const es = document.documentElement.lang.startsWith('es');
  const say = (en, spanish) => es ? spanish : en;
  const tokens = value => Number.isSafeInteger(value) && value >= 0 ? new Intl.NumberFormat(es?'es-MX':'en-US').format(value) : '—';
  let choices = [], available = [], dirty = false;
  const showStatus = (message, state = 'info') => { status.textContent = message; status.dataset.state = state; };
  const element = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
  const changed = () => { dirty = true; showStatus(say('Unsaved changes', 'Cambios sin guardar'), 'unsaved'); };
  function select(values, selected, update) {
    const n = element('select', null, 'form-select form-select-sm');
    values.forEach(([value, name]) => n.add(new Option(name, value)));
    n.value = selected || ''; n.onchange = () => { update(n.value || null); changed(); }; return n;
  }
  function action(text, label, callback) {
    const n = element('button', text, 'btn btn-outline-secondary btn-sm');
    n.type = 'button'; n.title = label; n.setAttribute('aria-label', label); n.onclick = callback; return n;
  }
  function render() {
    rows.replaceChildren();
    choices.forEach((item, index) => {
      const tr = element('tr'), position = element('td', String(index + 1));
      const model = element('td');
      const label = element('input', null, 'form-control form-control-sm');
      label.value = item.label; label.maxLength = 120; label.setAttribute('aria-label', say('Model display name', 'Nombre del modelo'));
      label.oninput = () => { item.label = label.value; changed(); };
      model.append(label, element('small', item.model, 'text-muted d-block mt-1'));
      const effort = element('td');
      const options = [['',say('Provider default / fixed','Predeterminado / fijo')]];
      if (item.reasoning_supported) options.push(...[['none',say('None','Ninguno')],['minimal',say('Minimal','Mínimo')],['low',say('Light','Ligero')],['medium',say('Medium','Medio')],['high',say('High','Alto')],['xhigh',say('Extra high','Muy alto')]]);
      effort.append(select(options,item.reasoning_effort,value => item.reasoning_effort=value));
      const color = element('td'), input = element('input', null, 'form-control form-control-color');
      input.type='color'; input.value=item.color; input.setAttribute('aria-label',say('Model color','Color del modelo'));
      input.oninput=()=>{item.color=input.value;changed();};color.append(input);
      const enabled = element('td'), toggle = element('input',null,'form-check-input');
      toggle.type='checkbox';toggle.checked=item.enabled;toggle.setAttribute('aria-label',say('Enabled model','Modelo habilitado'));
      toggle.onchange=()=>{item.enabled=toggle.checked;if(!item.enabled)item.is_default=false;changed();render();};enabled.append(toggle);
      const preferred=element('td'), radio=element('input',null,'form-check-input');
      radio.type='radio';radio.name='catalogDefault';radio.checked=!!item.is_default;radio.disabled=!item.enabled;
      radio.setAttribute('aria-label',say('Default model','Modelo predeterminado'));
      radio.onchange=()=>{choices.forEach(c=>c.is_default=c===item);changed();render();};preferred.append(radio);
      const actions=element('td'), buttons=element('div',null,'d-flex gap-1');
      const move=direction=>{const target=index+direction;if(target<0||target>=choices.length)return;[choices[index],choices[target]]=[choices[target],choices[index]];changed();render();};
      const up=action('↑',say('Move earlier','Mover antes'),()=>move(-1)), down=action('↓',say('Move later','Mover después'),()=>move(1));
      up.disabled=index===0;down.disabled=index===choices.length-1;
      buttons.append(up,down,action('×',say('Remove from catalogue','Quitar del catálogo'),()=>{choices.splice(index,1);changed();render();}));actions.append(buttons);
      const inputTokens=element('td',tokens(item.context_length),'model-token-limits');
      const outputTokens=element('td',tokens(item.max_completion_tokens),'model-token-limits');
      inputTokens.title=say('Published context window; input and output share this capacity.','Ventana de contexto publicada; entrada y salida comparten esta capacidad.');
      outputTokens.title=say('Published maximum output; a dash means no published bound.','Salida máxima publicada; el guion indica que no hay un límite publicado.');
      if(decisions)tr.append(position,model,inputTokens,outputTokens,enabled,preferred,actions);
      else tr.append(position,model,effort,color,inputTokens,outputTokens,enabled,preferred,actions);
      rows.append(tr);
    });
    document.getElementById('saveModelsButton').disabled=!choices.length||!choices.some(c=>c.enabled)||choices.filter(c=>c.enabled&&c.is_default).length!==1;
  }
  async function jsonRequest(url, options) {
    const response=await fetch(url,options);let data;
    try{data=await response.json();}catch{throw new Error(say('The platform returned an invalid response.','La plataforma devolvió una respuesta inválida.'));}
    if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;
  }
  function renderProvider() {
    const query=search.value.trim().toLowerCase();
    const matching=available.filter(m=>(!decisions || m.vision) &&`${m.label} ${m.model}`.toLowerCase().includes(query));
    results.replaceChildren();
    matching.slice(0,60).forEach(item=>{
      const button=element('button',null,'model-provider-option');button.type='button';
      button.append(element('strong',item.label),element('small',item.model));
      const features=[item.vision?say('Text + images','Texto + imágenes'):say('Text','Texto'),`${tokens(item.context_length)} ${say('context tokens','tokens de contexto')} · ${tokens(item.max_completion_tokens)} ${say('maximum output','salida máxima')}`];
      button.append(element('small',features.join(' · ')));
      button.onclick=()=>{if(choices.length>=32){showStatus(say('Maximum: 32 choices.','Máximo: 32 opciones.'), 'error');return;}
        choices.push({...item,id:decisions?item.model:`choice-${crypto.randomUUID()}`,enabled:true,is_default:choices.length===0,tier:'high',reasoning_effort:null,color:'#2686c9'});changed();render();picker.hidden=true;};
      button.disabled=decisions&&choices.some(c=>c.model===item.model);results.append(button);
    });
    if(!matching.length)results.append(element('p',say('No matching models.','Sin modelos coincidentes.')));
    else if(matching.length>60)results.append(element('p',say('Refine the search to see more models.','Afina la búsqueda para ver más modelos.')));
  }
  const revealPicker = () => picker.scrollIntoView({block:'start',behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  document.getElementById('discoverModelsButton').onclick=async()=>{
    const button=document.getElementById('discoverModelsButton');
    if(button.disabled)return;
    const done=window.warpButtonBusy(button);
    picker.hidden=false;results.replaceChildren();
    providerStatus.textContent=say('Loading provider catalogue…','Cargando catálogo del proveedor…');
    revealPicker();
    search.focus({preventScroll:true});
    try{available=(await jsonRequest(`${endpoint}/discover`)).models;renderProvider();providerStatus.textContent=say('Choose a model to add.','Selecciona un modelo para agregarlo.');
      // The loaded list increases page height; finish revealing the panel only
      // if the researcher is still using its search, not after closing/leaving it.
      if(!picker.hidden&&document.activeElement===search)revealPicker();}
    catch(error){providerStatus.textContent=error.message;}finally{done();}
  };
  document.getElementById('closeProviderPicker').onclick=()=>picker.hidden=true;
  search.oninput=renderProvider;
  document.getElementById('saveModelsButton').onclick=async()=>{
    const button=document.getElementById('saveModelsButton');
    if(button.disabled)return;
    const done=window.warpButtonBusy(button);
    showStatus(say('Saving model catalogue…','Guardando catálogo de modelos…'));
    try{choices=(await jsonRequest(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choices})})).choices;dirty=false;render();showStatus('');window.warpNotify(say('Model catalogue saved. Existing runs retain their frozen model configuration.','Catálogo de modelos guardado. Las corridas existentes conservan su configuración de modelos.'), 'success');}
    catch(error){showStatus(dirty?say('Unsaved changes','Cambios sin guardar'):'', 'unsaved');window.warpNotify(error.message, 'danger');}finally{done();}
  };
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  const initial=document.getElementById('initialModelChoices');
  if(initial){choices=JSON.parse(initial.textContent);render();}
  else jsonRequest(endpoint).then(data=>{choices=data.choices;render();}).catch(error=>showStatus(error.message, 'error'));
})();
