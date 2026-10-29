// Recorded event updates; polling is only a legacy-browser fallback. Keep expanded evidence, focus and scroll position.
(() => {
  const active = node => ['queued', 'running'].includes(node?.dataset.runStatus);
  const key = detail => `${detail.closest('[data-iteration-id]')?.dataset.iterationId || 'run'}:${detail.dataset.reportPanel || detail.querySelector('summary')?.textContent.trim()}`;
  const previews = root => root.querySelectorAll('.page-preview').forEach(link => {
    const preview = link.querySelector('.page-preview-popover');
    if (!preview) return;
    const position = event => {
      const anchor = link.getBoundingClientRect(), margin = 16, gap = 18;
      const x = event.clientX ?? anchor.right, y = event.clientY ?? anchor.top;
      const rightSpace = window.innerWidth-x-gap-margin;
      const width = Math.min(640, window.innerWidth - 2 * margin);
      preview.style.width = `${width}px`;
      const left = rightSpace >= width ? x+gap :
        Math.max(margin, Math.min(x-gap-width, window.innerWidth-width-margin));
      const height = preview.getBoundingClientRect().height;
      preview.style.setProperty('--preview-left',`${left}px`);
      preview.style.setProperty('--preview-top',`${Math.max(margin,Math.min(y,window.innerHeight-height-margin))}px`);
    };
    ['pointerenter','pointermove','focus'].forEach(event => link.addEventListener(event,position));
  });
  let root = document.getElementById('remediationReport');
  previews(root || document);
  if (!root) return;
  let controller,stream,busy=false,pending=false;
  const pushed=Boolean(window.EventSource&&root.dataset.liveEventsUrl);
  const refresh = async () => {
    if (!active(root)) {stream?.close();return;}
    if(busy){pending=true;return;}
    if (!document.hidden && !document.getSelection()?.toString() &&
        !root.querySelector('input:focus,textarea:focus,select:focus,[contenteditable]:focus')) {
      busy=true;pending=false;controller = new AbortController();
      const deadline = setTimeout(() => controller.abort(), 15000);
      try {
        const url = new URL(window.location.href); url.searchParams.set('live','1');
        const response = await fetch(url, {signal: controller.signal, cache:'no-store', headers:{Accept:'text/html'}});
        if (!response.ok) throw new Error('Report refresh failed');
        const next = new DOMParser().parseFromString(await response.text(),'text/html').getElementById('remediationReport');
        if (!next || !next.dataset.runStatus) throw new Error('Incomplete report');
        const open = new Set(Array.from(root.querySelectorAll('details[open]'),key));
        const focused = document.activeElement?.closest('details');
        const focusKey = focused && root.contains(focused) ? key(focused) : null;
        const scroll = window.scrollY;
        const scrolls=['.live-loop-evidence','.agentic-log-scroll'].map(selector=>[selector,root.querySelector(selector)?.scrollTop||0]);
        if(window.prepareLiveMotion)window.prepareLiveMotion(root,next);
        else {const previousFlow=root.querySelector('[data-flow-revision]')?.dataset.flowRevision;const nextFlow=next.querySelector('[data-flow-revision]');if(nextFlow&&nextFlow.dataset.flowRevision!==previousFlow)nextFlow.classList.add('is-new-activity');}
        next.querySelectorAll('details').forEach(detail => { detail.open = open.has(key(detail)); });
        root.replaceWith(next); root = next; previews(root);window.alignLiveMotion?.(root);
        scrolls.forEach(([selector,top])=>{const panel=root.querySelector(selector);if(panel)panel.scrollTop=top;});
        if (focusKey) Array.from(root.querySelectorAll('details')).find(detail => key(detail)===focusKey)?.querySelector('summary')?.focus({preventScroll:true});
        window.scrollTo({top:scroll,behavior:'instant'});
      } catch (_) {
        // Preserve the last valid report; temporary failures are retried.
      } finally { clearTimeout(deadline);busy=false; }
    }
    if(!active(root))stream?.close();
    else if(pushed&&pending&&!document.hidden&&!document.getSelection()?.toString())refresh();
    else if(!pushed)setTimeout(refresh,4000);
  };
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-stop-run]');
    if (!form || !root.contains(form)) return;
    event.preventDefault();
    const button = form.querySelector('button');
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = button.dataset.stoppingLabel;
    const message = form.querySelector('[data-stop-message]');
    message.hidden = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}
      });
      if (!response.ok) throw new Error('Stop request failed');
      pending = true;
      await refresh();
    } catch (_) {
      button.disabled = false;
      button.textContent = button.dataset.stopLabel;
      message.textContent = message.dataset.error;
      message.hidden = false;
    }
  });
  if(active(root)&&pushed){
    stream=new window.EventSource(root.dataset.liveEventsUrl);
    stream.addEventListener('activity',()=>{pending=true;refresh();});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&pending)refresh();});
    document.addEventListener('selectionchange',()=>{if(pending&&!document.getSelection()?.toString())refresh();});
  }else if(active(root))setTimeout(refresh,4000);
  window.addEventListener('pagehide',() => {controller?.abort();stream?.close();},{once:true});
})();
