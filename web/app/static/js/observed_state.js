/* Derived saved-page transport. Never loaded by the main application or evaluator. */
(() => {
    const record = document.querySelector('script[data-harness-observed-state]');
    if (!record) return;
    const state = JSON.parse(record.textContent);
    const pathPattern = /^html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9]\d*\))+$/;
    const stable = value => {
        if (Array.isArray(value)) return value.map(stable);
        if (value && typeof value === 'object') {
            return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
        }
        return value;
    };
    const equal = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
    const connected = new WeakSet();
    const loadedMedia = new WeakSet();
    const restore = () => {
        for (const reference of state.media || []) {
            if (!pathPattern.test(reference.path) || !/^[a-f0-9]{64}$/.test(reference.sha256)
                    || !Number.isFinite(reference.time) || reference.time < 0 || reference.time > 86400) continue;
            const targets = document.querySelectorAll(reference.path);
            if (targets.length !== 1 || targets[0].tagName !== 'VIDEO') continue;
            const video = targets[0];
            const expected = new URL(`assets/${reference.sha256}`, document.baseURI).href;
            const sources = Array.from(video.querySelectorAll('source'));
            const src = video.getAttribute('src') || (sources.length === 1 && sources[0].getAttribute('src'));
            if (!src || new URL(src, document.baseURI).href !== expected
                    || (video.hasAttribute('src') && sources.length) || loadedMedia.has(video)) continue;
            loadedMedia.add(video);
            const hero = video.closest('.b-hero');
            const buttons = pathPattern.test(reference.control || '') ? document.querySelectorAll(reference.control) : [];
            const button = buttons.length === 1 && buttons[0].tagName === 'BUTTON'
                && buttons[0].getAttribute('data-js') === 'video-trigger'
                && buttons[0].closest('.b-hero') === hero
                && reference.binding_sha256 === 'fdf88d0ffda34c9202f164105f2965d3d30b2f3ffe773c9bc78a8abce0096132'
                ? buttons[0] : null;
            const updateButton = () => {
                if (!button) return;
                hero.classList.toggle('video-paused', video.paused);
                button.setAttribute('aria-label', video.paused ? 'Play the video' : 'Pause the video');
            };
            let restored = false;
            let matched = false;
            const finish = () => {
                if (!matched || restored || video.readyState < 2 || video.seeking
                        || Math.abs(video.currentTime - reference.time) > 0.03) return;
                restored = true;
                video.pause();
                updateButton();
                record.dataset.restoredMedia = String(Number(record.dataset.restoredMedia || 0) + 1);
            };
            video.addEventListener('loadedmetadata', () => {
                if (video.videoWidth !== reference.width || video.videoHeight !== reference.height
                        || Number.isNaN(video.duration) || reference.time > video.duration) return;
                matched = true;
                video.pause();
                video.currentTime = reference.time;
                finish();
            }, {once: true});
            video.addEventListener('loadeddata', finish);
            video.addEventListener('seeked', finish);
            if (button) {
                button.addEventListener('click', async event => {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    if (video.paused) {
                        try { await video.play(); }
                        catch { record.dataset.mediaPlayback = 'unavailable'; }
                    } else video.pause();
                    updateButton();
                }, true);
                video.addEventListener('play', updateButton);
                video.addEventListener('pause', updateButton);
            }
            video.autoplay = false;
            video.preload = 'auto';
            video.load();
        }
        let restored = 0;
        for (const reference of state.animations) {
            if (!pathPattern.test(reference.path) || reference.paused !== true
                    || !Number.isFinite(reference.time) || reference.time < 0
                    || reference.time > 31536000000 || reference.pseudo) continue;
            if (state.animations.filter(other => other.path === reference.path
                    && other.name === reference.name && other.pseudo === reference.pseudo).length !== 1) continue;
            const targets = document.querySelectorAll(reference.path);
            if (targets.length !== 1) continue;
            const matches = targets[0].getAnimations().filter(animation => {
                if (!(animation instanceof CSSAnimation) || animation.effect.target !== targets[0]
                        || animation.animationName !== reference.name) return false;
                const timing = Object.fromEntries(Object.entries(animation.effect.getTiming())
                    .map(([key, value]) => [key, value === Infinity ? 'Infinity' : value]));
                return equal(animation.effect.getKeyframes(), reference.keyframes)
                    && equal(timing, reference.timing);
            });
            if (matches.length !== 1) continue;
            matches[0].pause();
            matches[0].currentTime = reference.time;
            restored++;
        }
        let aligned = 0;
        for (const carousel of state.carousels) {
            if (!pathPattern.test(carousel.path)) continue;
            const track = document.querySelector(carousel.path);
            const slides = track && Array.from(track.children);
            if (!slides || slides.length !== carousel.count || !slides[carousel.active]) continue;
            if (slides.some((slide, index) => getComputedStyle(slide).flexBasis !== '100%'
                    || slide.style.opacity !== (index === carousel.active ? '1' : '0'))) continue;
            let current = carousel.active;
            const controls = (carousel.controls || []).flatMap(control => {
                if (!pathPattern.test(control.path) || !Number.isInteger(control.index)
                        || control.index < 0 || control.index >= slides.length) return [];
                const matches = document.querySelectorAll(control.path);
                if (matches.length !== 1 || matches[0].tagName !== 'BUTTON'
                        || matches[0].getAttribute('@click') !== control.action
                        || control.action !== `emblaCarousel.scrollTo(${control.index})`
                        || matches[0].closest('[x-ref="embla"]') !== track.parentElement) return [];
                return [{button:matches[0], index:control.index}];
            });
            const select = index => {
                current = index;
                slides.forEach((slide, slideIndex) => {
                    // Percentage offsets follow each slide's width, including later resizes.
                    slide.style.transform = `translateX(${-100 * slideIndex}%)`;
                    slide.style.opacity = slideIndex === index ? '1' : '0';
                    slide.style.pointerEvents = slideIndex === index ? 'auto' : 'none';
                });
                for (const control of controls) {
                    const selected = control.index === index;
                    const classes = control.button.getAttribute(':class') || '';
                    if (classes.includes("'font-bold'")) control.button.classList.toggle('font-bold', selected);
                    if (classes.includes("'opacity-50'")) control.button.classList.toggle('opacity-50', !selected);
                    if (classes.includes("'opacity-100'")) control.button.classList.toggle('opacity-100', selected);
                    control.button.setAttribute('aria-current', selected ? 'true' : 'false');
                }
                track.dataset.harnessCurrentSlide = String(current);
            };
            // Keep the captured selection until a person explicitly operates a saved control.
            select(current);
            for (const control of controls) {
                if (connected.has(control.button)) continue;
                connected.add(control.button);
                control.button.addEventListener('click', event => {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    select(control.index);
                    record.dataset.slideInteractions = String(Number(record.dataset.slideInteractions || 0) + 1);
                }, true);
            }
            aligned++;
        }
        record.dataset.restoredAnimations = String(restored);
        record.dataset.alignedCarousels = String(aligned);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restore, {once: true});
    else restore();
    window.addEventListener('load', restore, {once: true});
})();
