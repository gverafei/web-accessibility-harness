/* Keep compact metric details available by pointer and keyboard. */
(function () {
    'use strict';
    const cards = document.querySelectorAll('[data-compact-details] .research-metric');
    if (!cards.length) return;
    const tooltip = document.createElement('div');
    tooltip.id = 'metricDetailTooltip';
    tooltip.className = 'metric-detail-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.hidden = true;
    document.body.append(tooltip);
    let current, dismissed, timer;

    function hide() {
        clearTimeout(timer);
        current?.removeAttribute('aria-describedby');
        current = null;
        tooltip.hidden = true;
    }
    function show(card) {
        if (card === dismissed) return;
        hide();
        current = card;
        tooltip.textContent = card.dataset.metricDetails;
        tooltip.hidden = false;
        const bounds = card.getBoundingClientRect();
        const size = tooltip.getBoundingClientRect();
        tooltip.style.left = Math.max(12, Math.min(bounds.left, innerWidth-size.width-12)) + 'px';
        tooltip.style.top = (bounds.bottom+size.height+8 < innerHeight
            ? bounds.bottom+8 : Math.max(12,bounds.top-size.height-8)) + 'px';
        card.setAttribute('aria-describedby', tooltip.id);
    }
    function leave() {
        dismissed = null;
        timer = setTimeout(hide, 150);
    }
    cards.forEach(card => {
        const details = [...card.querySelectorAll(':scope > small')].map(item => item.textContent.trim()).filter(Boolean);
        const explanation = card.querySelector(':scope > span[title]');
        if (explanation) {
            details.push('', explanation.title);
            explanation.removeAttribute('title');
        }
        if (!details.length) return;
        card.dataset.metricDetails = details.join('\n');
        card.tabIndex = 0;
        card.addEventListener('mouseenter', () => show(card));
        card.addEventListener('focus', () => show(card));
        card.addEventListener('mouseleave', leave);
        card.addEventListener('blur', () => { dismissed = null; hide(); });
    });
    tooltip.addEventListener('mouseenter', () => clearTimeout(timer));
    tooltip.addEventListener('mouseleave', leave);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') { dismissed = current; hide(); }
    });
    window.addEventListener('resize', hide);
    document.addEventListener('scroll', hide, true);
})();
