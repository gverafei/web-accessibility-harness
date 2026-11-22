/* Shared labels for ordinary numeric bars; dense charts keep their tooltips. */
(function (root) {
    'use strict';
    const plugin = {
        id: 'barValueLabels',
        afterDatasetsDraw(chart) {
            if (chart.config.plugins?.some(p => p.id === 'commonErrorValueLabels')) return;
            const {ctx, chartArea: area} = chart;
            const occupied = [];
            const theme = root.document?.documentElement.getAttribute('data-theme');
            const dark = theme === 'dark' || (theme === 'system' && root.matchMedia?.('(prefers-color-scheme: dark)').matches);
            ctx.save();
            ctx.font = '400 12px system-ui';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            chart.data.datasets.forEach((dataset, di) => {
                const meta = chart.getDatasetMeta(di);
                if (meta.type !== 'bar' || !chart.isDatasetVisible(di)) return;
                meta.data.forEach((bar, i) => {
                    const value = dataset.data[i];
                    // Floating bars are intervals, not individual measurements.
                    if (typeof value !== 'number' || !Number.isFinite(value)) return;
                    const horizontal = bar.horizontal;
                    const thickness = horizontal ? bar.height : bar.width;
                    const length = Math.abs((horizontal ? bar.x : bar.y) - bar.base);
                    const text = value.toLocaleString(root.document?.documentElement.lang || 'en',
                        {maximumFractionDigits: 2});
                    const width = ctx.measureText(text).width + 8, height = 18;
                    const stacked = meta.vScale?.options.stacked;
                    // Outside labels need room between labels, not inside the bar.
                    // Narrow grouped/Tranco bars may still have ample category space.
                    if (thickness < (horizontal ? height + 2 : stacked ? width + 2 : 12)) return;
                    if (stacked && (value === 0 || length < (horizontal ? width + 2 : height + 2))) return;
                    let x = bar.x, y = bar.y;
                    if (stacked) {
                        if (horizontal) x = (bar.x + bar.base) / 2;
                        else y = (bar.y + bar.base) / 2;
                    } else if (horizontal) {
                        x += (bar.x >= bar.base ? 1 : -1) * (width / 2 + 4);
                    } else {
                        y += (bar.y <= bar.base ? -1 : 1) * (height / 2 + 4);
                    }
                    // Keep labels inside the plotting area, including scores at the maximum.
                    x = Math.max(area.left + width / 2, Math.min(area.right - width / 2, x));
                    y = Math.max(area.top + height / 2, Math.min(area.bottom - height / 2, y));
                    const box = {left:x-width/2, right:x+width/2, top:y-height/2, bottom:y+height/2};
                    if (box.left < area.left || box.right > area.right || box.top < area.top || box.bottom > area.bottom) return;
                    if (occupied.some(b => box.left < b.right+2 && box.right > b.left-2 && box.top < b.bottom+2 && box.bottom > b.top-2)) return;
                    occupied.push(box);
                    // Light bars already use translucent fills: draw directly
                    // over them. Keep the dark-theme contrast backing unchanged.
                    if (dark) {
                        ctx.fillStyle = '#17212b';
                        ctx.fillRect(box.left, box.top, width, height);
                    }
                    ctx.fillStyle = dark ? '#f1f5f9' : '#17212b';
                    ctx.fillText(text, x, y);
                });
            });
            ctx.restore();
        }
    };
    if (root.Chart) root.Chart.register(plugin);
    if (typeof module !== 'undefined') module.exports = plugin;
})(typeof window !== 'undefined' ? window : globalThis);
