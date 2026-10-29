/* Review-only bindings for exact saved widget contracts; no publisher startup. */
(() => {
    const record = document.querySelector('script[data-harness-observed-state]');
    if (!record) return;
    const state = JSON.parse(record.textContent);
    const pathPattern = /^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9]\d*\))+$/;
    const node = path => {
        if (!pathPattern.test(path || '')) return null;
        const matches = document.querySelectorAll(path);
        return matches.length === 1 ? matches[0] : null;
    };
    const disclosures = [];
    for (const saved of state.widgets || []) {
        if (saved.kind === 'slick') continue;
        const trigger = node(saved.trigger), panel = node(saved.panel);
        if (!trigger || !panel || !['dropdown', 'collapse'].includes(saved.kind)) continue;
        const set = open => {
            panel.classList.toggle('show', open);
            trigger.classList.toggle('show', open);
            trigger.setAttribute('aria-expanded', String(open));
        };
        const item = {trigger, panel, set, kind: saved.kind};
        disclosures.push(item);
        trigger.addEventListener('click', event => {
            event.preventDefault();
            event.stopImmediatePropagation();
            const open = !panel.classList.contains('show');
            if (saved.kind === 'dropdown') {
                for (const other of disclosures) if (other !== item && other.kind === 'dropdown') other.set(false);
            }
            set(open);
        }, true);
        trigger.addEventListener('keydown', event => {
            if (event.key !== 'ArrowDown' || saved.kind !== 'dropdown') return;
            event.preventDefault();
            set(true);
            panel.querySelector('a[href], input, button')?.focus();
        });
    }
    document.addEventListener('click', event => {
        for (const item of disclosures) {
            if (item.kind === 'dropdown' && !item.panel.contains(event.target) && !item.trigger.contains(event.target)) item.set(false);
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        const focused = document.activeElement;
        const opened = disclosures.filter(item => item.panel.classList.contains('show')
            && (item.panel.contains(focused) || item.trigger === focused));
        const current = opened.find(item => !opened.some(other => other !== item && item.panel.contains(other.panel)));
        if (current) {
            event.preventDefault();
            current.set(false);
            current.trigger.focus();
        }
    });
    const localImage = element => {
        const raw = element.getAttribute('data-src');
        if (!raw) return;
        const url = new URL(raw, document.baseURI);
        if (url.origin !== location.origin || !/\/assets\/[a-f0-9]{64}$/.test(url.pathname)) return;
        if (element.tagName === 'IMG') { element.src = url.href; return; }
        element.style.backgroundImage = `url("${url.href}")`;
        element.style.backgroundSize = element.getAttribute('data-size') || 'cover';
        element.style.backgroundPosition = element.getAttribute('data-pos') || 'center';
    };
    for (const saved of state.widgets || []) {
        if (saved.kind !== 'slick') continue;
        const root = node(saved.root);
        const viewport = root?.querySelector(':scope > .slick-list');
        const track = viewport?.querySelector(':scope > .slick-track');
        const slides = track && Array.from(track.children);
        if (!slides || slides.length !== saved.count || !slides[saved.active]
                || slides.some((slide, index) => slide.getAttribute('data-slick-index') !== String(index))) continue;
        const prev = root.querySelector(':scope > .slick-prev');
        const next = root.querySelector(':scope > .slick-next');
        const dots = Array.from(root.querySelectorAll(':scope > .slick-dots > li'));
        let current = saved.active;
        let visible = saved.show, step = saved.step;
        const render = () => {
            [visible, step] = [saved.show, saved.step];
            for (const [breakpoint, count, advance] of saved.responsive) {
                if (innerWidth < breakpoint) [visible, step] = [count, advance];
            }
            visible = Math.min(visible, slides.length);
            current = Math.max(0, Math.min(current, slides.length - visible));
            const width = viewport.getBoundingClientRect().width / visible;
            if (!(width > 0)) return;
            track.style.width = `${width * slides.length}px`;
            track.style.transform = `translate3d(${-current * width}px,0,0)`;
            for (const [index, slide] of slides.entries()) {
                const active = index >= current && index < current + visible;
                slide.style.width = `${width}px`;
                slide.classList.toggle('slick-active', active);
                slide.classList.toggle('slick-current', index === current);
                slide.setAttribute('aria-hidden', String(!active));
                if (active) {
                    slide.querySelectorAll('.slide-image, img[data-src]').forEach(image => {
                        const mediaType = image.getAttribute('tipo_media');
                        if (image.tagName === 'IMG' || mediaType === null || mediaType === '' || mediaType === '1') {
                            localImage(image);
                        }
                    });
                }
            }
            for (const [button, disabled] of [[prev, current === 0], [next, current >= slides.length - visible]]) {
                if (!button) continue;
                button.classList.toggle('slick-disabled', disabled);
                button.setAttribute('aria-disabled', String(disabled));
                if (button.tagName === 'BUTTON') button.disabled = disabled;
            }
            for (const [index, dot] of dots.entries()) {
                const active = index === Math.ceil(current / step);
                dot.classList.toggle('slick-active', active);
                const button = dot.querySelector('button');
                if (button) button.setAttribute('aria-selected', String(active));
            }
            root.dataset.savedSlide = String(current);
        };
        const move = index => { current = index; render(); };
        for (const [button, direction] of [[prev, -1], [next, 1]]) {
            button?.addEventListener('click', event => {
                event.preventDefault(); event.stopImmediatePropagation();
                move(current + direction * step);
            }, true);
        }
        dots.forEach((dot, index) => dot.querySelector('button')?.addEventListener('click', event => {
            event.preventDefault(); event.stopImmediatePropagation(); move(index * step);
        }, true));
        let start = null;
        viewport.addEventListener('pointerdown', event => { start = [event.clientX, event.clientY]; });
        viewport.addEventListener('pointerup', event => {
            if (!start) return;
            const dx = event.clientX - start[0], dy = event.clientY - start[1];
            start = null;
            if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) move(current + (dx < 0 ? step : -step));
        });
        window.addEventListener('resize', render);
        render();
    }
})();
