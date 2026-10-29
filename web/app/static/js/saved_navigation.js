/* Only the fingerprinted captured disclosure contract, in derived review copies. */
(() => {
    const record = document.querySelector('script[data-harness-observed-state]');
    if (!record) return;
    const state = JSON.parse(record.textContent);
    const pathPattern = /^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9]\d*\))+$/;
    const one = path => {
        if (!pathPattern.test(path || '')) return null;
        const nodes = document.querySelectorAll(path);
        return nodes.length === 1 ? nodes[0] : null;
    };
    const restore = () => {
        for (const binding of state.navigation || []) {
            if (binding.binding_sha256 !== 'c944a9e17a7f5b32a52eaab8ffafa992c6e7cd8bd9563a5cc4d6ba78f4f0d8ba'
                    || binding.stylesheet_sha256 !== '0e203130cf01c6710373046614ae8356614e5f4bd7bef03c5f38a7bbcf1e79d9') continue;
            const panel = one(binding.panel), header = one(binding.header), nav = one(binding.nav);
            const open = one(binding.open), close = one(binding.close);
            if (!panel || !header || !nav || !open || !close || panel.id !== 'site-nav'
                    || open.tagName !== 'BUTTON' || close.tagName !== 'BUTTON'
                    || open.getAttribute('aria-controls') !== panel.id
                    || close.getAttribute('aria-controls') !== panel.id || !panel.contains(nav)) continue;
            const children = (binding.children || []).flatMap(item => {
                const trigger = one(item.trigger), child = one(item.panel), back = one(item.back);
                if (!trigger || !child || !back || !nav.contains(trigger) || !nav.contains(child)
                        || trigger.getAttribute('aria-controls') !== child.id
                        || child.getAttribute('aria-labelledby') !== trigger.id
                        || back.getAttribute('aria-controls') !== child.id || !child.contains(back)
                        || ![0,1].includes(item.depth)) return [];
                return [{trigger, child, back, depth:item.depth, group:trigger.parentElement,
                    parent:child.parentElement, next:child.nextSibling, active:false}];
            });
            let active = false, overflow = '';
            const outside = Array.from(document.querySelectorAll('.site-header__brand,#main-content,.site-footer'));
            const inertBefore = new Map(outside.map(element=>[element,element.inert]));
            const closeChild = item => {
                item.active = false;
                item.child.setAttribute('aria-hidden','true');
                item.trigger.setAttribute('aria-expanded','false');
                item.back.setAttribute('aria-expanded','false');
                item.group.classList.remove('nav-primary__item--child-active');
                item.parent.insertBefore(item.child, item.next && item.next.parentNode === item.parent ? item.next : null);
            };
            const updateChildren = () => {
                nav.classList.toggle('site-nav--child-active',children.some(item=>item.active));
                for (const depth of [0,1]) {
                    nav.classList.toggle(`site-nav--child-active-depth-${depth}`,children.some(item=>item.active && item.depth===depth));
                    nav.querySelector(`.nav-primary__col-${depth+1}`)?.classList.toggle('nav-primary__col--rendered',children.some(item=>item.active && item.depth===depth));
                }
            };
            const setOpen = value => {
                active = value;
                panel.setAttribute('aria-hidden',String(!value));
                open.setAttribute('aria-expanded',String(value));
                close.setAttribute('aria-expanded',String(value));
                header.classList.toggle('site-nav--is-open',value);
                header.classList.toggle('site-nav--is-active',value);
                for (const element of outside) element.inert = value || inertBefore.get(element);
                if (value) { overflow=document.body.style.overflow; document.body.style.overflow='hidden'; }
                else {
                    document.body.style.overflow=overflow;
                    children.filter(item=>item.active).sort((a,b)=>b.depth-a.depth).forEach(closeChild);
                    updateChildren();
                }
                (value ? nav.querySelector('.nav-primary__action--depth-0') : open)?.focus();
                record.dataset.localNavigation = value ? 'open' : 'closed';
            };
            const click = (element, action) => element.addEventListener('click',event=>{
                event.preventDefault(); event.stopImmediatePropagation(); action();
            },true);
            click(open,()=>setOpen(!active));
            click(close,()=>setOpen(false));
            for (const item of children) {
                click(item.trigger,()=>{
                    const wasActive=item.active;
                    children.filter(other=>other.active && other.depth>=item.depth).sort((a,b)=>b.depth-a.depth).forEach(closeChild);
                    if (!wasActive) {
                        item.active=true;
                        item.child.setAttribute('aria-hidden','false');
                        item.trigger.setAttribute('aria-expanded','true');
                        item.back.setAttribute('aria-expanded','true');
                        item.group.classList.add('nav-primary__item--child-active');
                        if (matchMedia('(min-width:768px)').matches) nav.querySelector(`.nav-primary__col-${item.depth+1}`)?.append(item.child);
                        item.child.querySelector('a[href],button:not(.nav-primary__back-action)')?.focus();
                    }
                    updateChildren();
                });
                click(item.back,()=>{
                    children.filter(other=>other.active && other.depth>=item.depth).sort((a,b)=>b.depth-a.depth).forEach(closeChild);
                    updateChildren(); item.trigger.focus();
                });
            }
            document.addEventListener('keydown',event=>{
                if (!active || event.key !== 'Escape') return;
                const last=children.filter(item=>item.active).sort((a,b)=>b.depth-a.depth)[0];
                if (last) { closeChild(last); updateChildren(); last.trigger.focus(); }
                else setOpen(false);
                event.preventDefault();
            });
        }
    };
    if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',restore,{once:true});
    else restore();
})();
