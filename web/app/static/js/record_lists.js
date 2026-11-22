'use strict';
// Shared presentation-only pagination for complete analytical tables.
const RECORD_PAGE_SIZES=[5,10,25,50,100,200];
const RECORD_PAGE_SIZE_KEY='history-list-page-size';
function savedRecordPageSize(env, fallback=5) {
  let saved;try{saved=env.localStorage.getItem(RECORD_PAGE_SIZE_KEY);}catch(_){}
  return RECORD_PAGE_SIZES.includes(Number(saved))?Number(saved):
    RECORD_PAGE_SIZES.includes(Number(fallback))?Number(fallback):5;
}
function saveRecordPageSize(env, value) {
  if(!RECORD_PAGE_SIZES.includes(Number(value)))return;
  try{env.localStorage.setItem(RECORD_PAGE_SIZE_KEY,String(value));}catch(_){}
}
function matchesRecordQuery(group, query) {
  const value = String(query).trim();
  const encoded = group.entry?.dataset.searchIds;
  const id = value.match(/^(?:(run|corrida|ejecuci[oó]n|iteration|iteraci[oó]n|iter)\s*[:#]?\s*)?#?(\d+)$/i);
  if (encoded && id) {
    let ids;
    try { ids = JSON.parse(encoded); } catch (_) { return false; }
    if (!ids || typeof ids !== 'object' || Array.isArray(ids)) return false;
    const number = id[2].replace(/^0+(?=\d)/, '');
    const run = String(ids.run) === number;
    const iteration = Array.isArray(ids.iterations) && ids.iterations.some(item => String(item) === number);
    if (!id[1]) return run || iteration;
    return /^(run|corrida|ejecuci[oó]n)$/i.test(id[1]) ? run : iteration;
  }
  return group.text.toLocaleLowerCase().includes(value.toLocaleLowerCase());
}
function recordPage(groups, query, page, size) {
  const allowed=RECORD_PAGE_SIZES;size=allowed.includes(Number(size))?Number(size):5;
  const selected=groups.filter(g=>matchesRecordQuery(g,query));
  const pages=Math.max(1,Math.ceil(selected.length/size));page=Math.max(1,Math.min(pages,Number(page)||1));
  return {items:selected.slice((page-1)*size,page*size),page,pages,total:selected.length,size};
}
if(typeof module!=='undefined')module.exports={recordPage,matchesRecordQuery};
if(typeof document!=='undefined')document.querySelectorAll('form[data-server-list]').forEach(form=>{
  let timer,controller;
  const results=form.nextElementSibling;
  if(!results?.matches('[data-list-results]'))return;
  function url(){const target=new URL(location.href);target.search=new URLSearchParams(new FormData(form)).toString();target.searchParams.set('page','1');return target;}
  async function update(target){
    controller?.abort();controller=new AbortController();results.setAttribute('aria-busy','true');
    try{
      const response=await fetch(target,{signal:controller.signal});if(!response.ok)throw new Error('List request failed');
      const parsed=new DOMParser().parseFromString(await response.text(),'text/html');
      const fresh=parsed.querySelector('[data-list-results]'),bar=parsed.querySelector('form[data-server-list]');
      if(!fresh||!bar)throw new Error('Missing list response');
      results.replaceChildren(...fresh.childNodes);
      form.querySelector('.listing-pagination').replaceWith(bar.querySelector('.listing-pagination'));
      form.querySelector('.listing-total').textContent=bar.querySelector('.listing-total').textContent;
      history.replaceState(null,'',target);results.removeAttribute('aria-busy');
    }catch(error){if(error.name!=='AbortError'){results.removeAttribute('aria-busy');window.warpNotify?.(document.documentElement.lang==='es'?'No se pudo actualizar el listado.':'Unable to update this list.','danger');}}
  }
  const search=form.elements.namedItem('q');
  search.addEventListener('input',()=>{clearTimeout(timer);controller?.abort();timer=setTimeout(()=>update(url()),250);});
  form.addEventListener('change',event=>{if(event.target.matches('select')){clearTimeout(timer);update(url());}});
  form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);update(url());});
  form.addEventListener('click',event=>{const link=event.target.closest('.listing-pagination a');if(link){event.preventDefault();clearTimeout(timer);update(new URL(link.href));}});
});
if(typeof document!=='undefined')document.querySelectorAll('table[data-client-list]').forEach((table,index)=>{
  const es=document.documentElement.lang==='es',t=(en,spa)=>es?spa:en;
  const rows=[...table.tBodies[0]?.rows||[]],groups=[];
  rows.forEach(row=>{
    if(row.classList.contains('record-actions-row')&&groups.length)groups.at(-1).rows.push(row);
    else groups.push({rows:[row],text:row.textContent});
  });
  const key='table'+index+'_',url=new URL(location.href);
  const toolbar=document.createElement('form');toolbar.className='listing-toolbar';toolbar.setAttribute('role','search');
  const search=document.createElement('input');search.type='search';search.className='form-control';search.value=url.searchParams.get(key+'q')||'';
  const searchLabel=document.createElement('label');searchLabel.className='listing-search';const searchCaption=document.createElement('span');searchCaption.textContent=t('Search records','Buscar registros');searchLabel.append(searchCaption,search);
  const size=document.createElement('select');size.className='form-select';size.setAttribute('aria-label',t('Per page','Por página'));
  RECORD_PAGE_SIZES.forEach(v=>size.add(new Option(v,v)));size.value=savedRecordPageSize(window,url.searchParams.get(key+'size'));
  const sizeLabel=document.createElement('label');sizeLabel.className='listing-size';const sizeCaption=document.createElement('span');sizeCaption.textContent=t('Per page','Por página');sizeLabel.append(sizeCaption,size);
  const total=document.createElement('span');total.className='listing-total';total.setAttribute('aria-live','polite');toolbar.append(searchLabel,sizeLabel);
  const pager=document.createElement('nav');pager.className='listing-pagination';pager.setAttribute('aria-label',t('Pagination','Paginación'));
  const previous=document.createElement('button'),next=document.createElement('button'),caption=document.createElement('span');
  previous.type=next.type='button';previous.className=next.className='btn';previous.textContent='‹';next.textContent='›';previous.setAttribute('aria-label',t('Previous','Anterior'));next.setAttribute('aria-label',t('Next','Siguiente'));previous.title=t('Previous','Anterior');next.title=t('Next','Siguiente');pager.append(previous,next,caption);toolbar.append(pager,total);
  let page=Number(url.searchParams.get(key+'page'))||1;
  function render(){
    const result=recordPage(groups,search.value,page,size.value);page=result.page;
    groups.forEach(g=>g.rows.forEach(row=>row.hidden=!result.items.includes(g)));
    caption.textContent=t('Page','Página')+' '+page+' / '+result.pages;total.textContent=result.total+' '+t('records','registros');previous.disabled=page<=1;next.disabled=page>=result.pages;
    const current=new URL(location.href);current.searchParams.set(key+'page',page);current.searchParams.set(key+'q',search.value);current.searchParams.set(key+'size',size.value);history.replaceState(null,'',current);
  }
  previous.addEventListener('click',()=>{page--;render();});next.addEventListener('click',()=>{page++;render();});
  search.addEventListener('input',()=>{page=1;render();});size.addEventListener('change',()=>{saveRecordPageSize(window,size.value);page=1;render();});toolbar.addEventListener('submit',e=>{e.preventDefault();page=1;render();});
  table.parentElement.before(toolbar);render();
});

function matchesHistoryFilters(entry, strategy, preservation) {
  if(!strategy&&!preservation)return true;
  let pairs=[];try{pairs=JSON.parse(entry.dataset.filterPairs||'[]');}catch(_){return false;}
  return Array.isArray(pairs)&&pairs.some(pair=>Array.isArray(pair)&&(!strategy||pair[0]===strategy)&&(!preservation||pair[1]===preservation));
}
function matchesRecordFilters(entry, selects) {
  return selects.every(select=>{
    if(!select.value)return true;
    const value=entry.dataset[select.dataset.historyFilter]||'';
    return select.dataset.historyMatch==='tokens'?value.split(/\s+/).includes(select.value):value===select.value;
  });
}
function matchesRagFilter(entry, usage) {
  return !usage || entry.dataset.ragUsed === usage;
}
function matchesEvaluationFilters(entry, status, acquisition) {
  return (!status||entry.dataset.status===status)&&(!acquisition||entry.dataset.acquisition===acquisition);
}
// Histories paginate complete records in both table and card presentation.
function initHistoryPagination(pager, env=window) {
  const table=env.document.querySelector(pager.dataset.table);
  const input=env.document.getElementById(pager.dataset.input);
  const size=pager.querySelector('select'),status=pager.querySelector('.measurement-pagination-status');
  const buttons=[...pager.querySelectorAll('[data-page-action]')];
  const bar=pager.closest?.('.list-filter-bar');
  const strategy=bar?.querySelector('[data-history-strategy]'),preservation=bar?.querySelector('[data-history-preservation]');
  const state=bar?.querySelector('[data-history-status]'),acquisition=bar?.querySelector('[data-history-acquisition]');
  const rag=bar?.querySelector('[data-history-rag]'),kind=bar?.querySelector('[data-history-kind]');
  const custom=[...bar?.querySelectorAll?.('[data-history-filter]')||[]];
  const filters=[[rag,'Rag'],[strategy,'Strategy'],[preservation,'Preservation'],[state,'Status'],[acquisition,'Acquisition'],[kind,'Kind'],...custom.map(select=>[select,select.dataset.historyFilter])];
  const es=env.document.documentElement.lang==='es',t=(en,spa)=>es?spa:en;
  const prefix=pager.dataset.input, saved=new URL(env.location.href);
  const standard=pager.dataset.standardParams==='true';
  const param=key=>standard?({Query:'q',Size:'size',Page:'page',Status:'status',Kind:'kind'}[key]||key.toLowerCase()):prefix+key;
  input.value=saved.searchParams.get(param('Query'))??input.value;
  const requestedSize=saved.searchParams.get(param('Size'));
  size.value=standard&&RECORD_PAGE_SIZES.includes(Number(requestedSize))?Number(requestedSize):savedRecordPageSize(env,requestedSize);
  filters.forEach(([select,key])=>{if(select){
    let value=saved.searchParams.get(param(key))??(standard?select.value:'');
    if(standard&&key==='Status'&&value==='assigned')value='pending';
    select.value=[...select.options].some(option=>option.value===value)?value:(standard?select.value:'');
  }});
  let page=Number(saved.searchParams.get(param('Page')))||1;
  const stateView={filteredEntries:[],render};
  function render(reset=false) {
    if(reset)page=1;
    const groups=[...table.querySelectorAll('[data-history-entry]')].map(entry=>({entry,text:entry.dataset.searchText||entry.textContent}));
    const eligible=groups.filter(group=>matchesHistoryFilters(group.entry,strategy?.value||'',preservation?.value||'')&&matchesEvaluationFilters(group.entry,state?.value||'',acquisition?.value||'')&&matchesRagFilter(group.entry,rag?.value||'')&&(!kind?.value||group.entry.dataset.kind===kind.value)&&matchesRecordFilters(group.entry,custom));
    stateView.filteredEntries=eligible.filter(group=>matchesRecordQuery(group,input.value)).map(group=>group.entry);
    // Opt-in display positions follow this view, independently of saved record IDs.
    stateView.filteredEntries.forEach((entry,index)=>{
      const cell=entry.querySelector?.('[data-history-position]');
      if(cell)cell.textContent=String(index+1);
    });
    const result=recordPage(eligible,input.value.trim(),page,size.value);page=result.page;size.value=result.size;
    const empty=table.querySelector?.('[data-history-empty]');if(empty)empty.hidden=result.total>0;
    groups.forEach(group=>{group.entry.hidden=!result.items.includes(group);});
    const start=result.total?(page-1)*result.size+1:0,end=Math.min(page*result.size,result.total);
    status.textContent=`${t('Page','Página')} ${page} ${t('of','de')} ${result.pages} · ${start}–${end} / ${result.total}`;
    buttons.forEach(button=>{button.disabled=['first','previous'].includes(button.dataset.pageAction)?page===1:page===result.pages;});
    const url=new URL(env.location.href);url.searchParams.set(param('Page'),page);url.searchParams.set(param('Size'),result.size);url.searchParams.set(param('Query'),input.value);url.searchParams.delete(param('Strategy'));url.searchParams.delete(param('Preservation'));filters.forEach(([select,key])=>{if(select)url.searchParams.set(param(key),select.value);});env.history.replaceState(null,'',url);
    table.dispatchEvent(new Event('history:filtered'));
    return result;
  }
  function inPlace(update) {
    const top=pager.getBoundingClientRect().top;
    update();const result=render();
    env.requestAnimationFrame(()=>env.requestAnimationFrame(()=>env.scrollBy({top:pager.getBoundingClientRect().top-top,behavior:'instant'})));
    return result;
  }
  buttons.forEach(button=>button.addEventListener('click',()=>inPlace(()=>{
    const action=button.dataset.pageAction;
    page=action==='first'?1:action==='previous'?page-1:action==='next'?page+1:Number.MAX_SAFE_INTEGER;
  })));
  input.addEventListener('input',()=>inPlace(()=>{page=1;}));
  size.addEventListener('change',()=>inPlace(()=>{saveRecordPageSize(env,size.value);page=1;}));
  filters.forEach(([select])=>select?.addEventListener('change',()=>inPlace(()=>{page=1;})));
  pager.closest?.('form[role="search"]')?.addEventListener('submit',event=>{event.preventDefault();inPlace(()=>{page=1;});});
  table.addEventListener('history:changed',()=>render());
  table._historyPagination=stateView;render();return stateView;
}
if(typeof module!=='undefined')Object.assign(module.exports,{savedRecordPageSize,saveRecordPageSize,RECORD_PAGE_SIZES,initHistoryPagination,matchesRecordFilters,matchesHistoryFilters,matchesEvaluationFilters,matchesRagFilter});
if(typeof document!=='undefined')document.querySelectorAll('[data-history-pagination]').forEach(pager=>initHistoryPagination(pager));
