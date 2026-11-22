/* Recorded activity only: filters and refresh never invoke a model. */
(function () {
    'use strict';
    const panel = document.getElementById('dashboardActivity');
    if (!panel) return;
    const form = document.getElementById('dashboardFilters');
    const message = document.getElementById('dashboardMessage');
    const status = document.getElementById('dashboardStatus');
    const labels = JSON.parse(document.getElementById('dashboardActivityLabels').textContent);
    const charts = new Map();
    const visibility = new Map();
    const formatter = new Intl.NumberFormat(document.documentElement.lang, {maximumFractionDigits: 1});
    const compact = new Intl.NumberFormat(document.documentElement.lang, {notation:'compact',maximumFractionDigits:1});
    let data = JSON.parse(document.getElementById('dashboardActivityData').textContent);
    let controller;
    let revision = 0;
    let timer;
    let disposed = false;

    function value(number, digits = 1) {
        return number == null ? '—' : Number(number).toLocaleString(document.documentElement.lang,
            {minimumFractionDigits: digits, maximumFractionDigits: digits});
    }

    function duration(seconds) {
        const minutes = Math.round((seconds || 0) / 60);
        const hours = Math.floor(minutes / 60);
        return hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
    }

    function sparkline(values) {
        const numeric = values.filter(Number.isFinite);
        if (!numeric.length) return '';
        // Hold the last observation through inactive periods, without changing data.
        const first = values.findIndex(Number.isFinite);
        const low = Math.min(...numeric), span = Math.max(...numeric) - low;
        const recorded = values.slice(first);
        if (recorded.length === 1) return 'M3.0,24.0 L157.0,24.0';
        let latest = recorded[0];
        return recorded.map((number, index) => {
            if (Number.isFinite(number)) latest = number;
            const x = 3 + index * 154 / (recorded.length-1);
            const y = span ? 43 - (latest - low) * 38 / span : 24;
            return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
    }

    function trend(key, values) {
        const numeric = values.filter(Number.isFinite);
        if (!numeric.length) return 'unavailable';
        if (!['axe','evaluation_axe','lighthouse','evaluation_lighthouse'].includes(key)) return 'activity';
        const change = numeric.at(-1) - numeric[0];
        if (Math.abs(change) < 1e-9) return 'unchanged';
        const lowerIsBetter = key === 'axe' || key === 'evaluation_axe';
        return (change < 0) === lowerIsBetter ? 'improving' : 'worsening';
    }

    function cards() {
        panel.querySelectorAll('[data-dashboard-metric]').forEach(card => {
            const key = card.dataset.dashboardMetric;
            const number = data.totals[key];
            const formatted = key === 'cost' ? `$${value(number,4)}` : key === 'seconds'
                ? duration(number) : ['runs','evaluations'].includes(key) ? value(number,0) : value(number);
            card.querySelector('[data-metric-value]').textContent = formatted;
            const detail = card.querySelector('[data-metric-detail]');
            detail.textContent = key === 'runs' ? `${data.totals.completed} ${labels.completed} · ${data.totals.active} ${labels.active}`
                : key === 'cost' ? `${labels.evaluationCost} $${value(data.totals.evaluation_cost,4)} · ${labels.remediationCost} $${value(data.totals.remediation_cost,4)}` : '';
            const values = data.trends[key] || [];
            const line = card.querySelector('[data-metric-sparkline]');
            const graphic = card.querySelector('.metric-sparkline');
            const direction = trend(key,values);
            const description = `${labels.trend}: ${labels[direction]}`;
            line.setAttribute('d',sparkline(values));
            graphic.dataset.trend = direction;
            graphic.setAttribute('aria-label',description);
            graphic.querySelector('[data-metric-trend-label]').textContent = description;
            graphic.toggleAttribute('hidden',direction === 'unavailable');
        });
    }

    function displayColor(color) {
        if (document.documentElement.dataset.theme !== 'dark') return color;
        return {'#215F97':'#5FA8F2','#7050A8':'#B18AF2','#B87316':'#F1B15A','#8996A8':'#BAC4D2','#C45D3E':'#F28A6B','#C13C83':'#F472B6','#667085':'#A3ADBC'}[color] || color;
    }

    function rankings() {
        ['models','strategies'].forEach(kind => {
            const list = panel.querySelector(`[data-dashboard-ranking="${kind}"]`);
            list.replaceChildren();
            data[kind].forEach(item => {
                const row = document.createElement('li');
                const identity = document.createElement('span');
                const dot = document.createElement('i');
                dot.style.background = displayColor(item.color || '#218A79');
                dot.setAttribute('aria-hidden','true');
                identity.append(dot, document.createTextNode(item.label || item.policy));
                const measure = document.createElement('small');
                measure.textContent = `${item.runs} ${labels.runs} · $${value(item.cost,4)}`;
                row.append(identity, measure);
                list.append(row);
            });
            if (!data[kind].length) list.textContent = labels.empty;
        });
    }

    function palette() {
        const css = getComputedStyle(document.documentElement);
        return {
            ink: css.getPropertyValue('--ui-ink').trim() || '#253442',
            muted: css.getPropertyValue('--ui-muted').trim() || '#65717B',
            surface: css.getPropertyValue('--ui-surface').trim() || '#FFFFFF',
            grid: css.getPropertyValue('--ui-line').trim() || '#D4D4D4'
        };
    }

    const quadrant = {
        id: 'attractiveQuadrant',
        beforeDatasetsDraw(chart) {
            if (!chart.options.plugins.attractiveQuadrant?.enabled) return;
            const {ctx,chartArea:area} = chart;
            const middleX = (area.left+area.right)/2;
            const middleY = (area.top+area.bottom)/2;
            ctx.save();
            ctx.fillStyle = 'rgba(45,167,88,.08)';
            const right = chart.options.plugins.attractiveQuadrant.highX;
            ctx.fillRect(right ? middleX : area.left, area.top, (area.right-area.left)/2, (area.bottom-area.top)/2);
            ctx.strokeStyle = 'rgba(75,145,100,.18)';
            ctx.lineWidth = .6;
            ctx.beginPath();ctx.moveTo(middleX,area.top);ctx.lineTo(middleX,area.bottom);
            ctx.moveTo(area.left,middleY);ctx.lineTo(area.right,middleY);ctx.stroke();
            ctx.restore();
        }
    };

    function legend(key, chart) {
        const container = panel.querySelector(`[data-chart-legend="${key}"]`);
        container.replaceChildren();
        chart.data.datasets.forEach((dataset,index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'activity-legend-button';
            button.setAttribute('aria-pressed', String(chart.isDatasetVisible(index)));
            const dot = document.createElement('i');
            dot.style.background = dataset.backgroundColor;
            dot.setAttribute('aria-hidden','true');
            button.append(dot, document.createTextNode(dataset.label));
            button.addEventListener('click', () => {
                const shown = !chart.isDatasetVisible(index);
                visibility.set(key+':'+dataset.profile,shown);
                chart.setDatasetVisibility(index,shown);
                chart.update('none');
                button.setAttribute('aria-pressed',String(shown));
            });
            container.append(button);
        });
        if (chart.options.plugins.attractiveQuadrant?.enabled) {
            const note = document.createElement('span');
            note.className = 'activity-quadrant-key';
            note.textContent = labels.quadrant;
            container.append(note);
        }
    }

    function draw(key, configuration) {
        const canvas = document.getElementById('dashboardChart-'+key);
        const colors = palette();
        configuration.options = {
            responsive: true, maintainAspectRatio: false, animation: false,
            color: colors.ink, interaction: {mode:'nearest',intersect:true},
            ...configuration.options,
            plugins: {legend:{display:false}, barValueLabels:false, ...configuration.options?.plugins}
        };
        for (const axis of Object.values(configuration.options.scales || {})) {
            axis.grid = {color:colors.grid+'66', ...axis.grid};
            axis.ticks = {color:colors.muted,font:{size:10}, ...axis.ticks};
            if (axis.title) axis.title.color = colors.ink;
        }
        let chart = charts.get(key);
        if (chart) {
            chart.data = configuration.data;
            chart.options = configuration.options;
        } else {
            chart = new Chart(canvas,{...configuration,plugins:[quadrant]});
            charts.set(key,chart);
        }
        chart.data.datasets.forEach((dataset,index) => {
            chart.setDatasetVisibility(index,visibility.get(key+':'+dataset.profile) !== false);
        });
        chart.update('none');
        const populated = chart.data.datasets.some(dataset => dataset.data.length);
        canvas.hidden = !populated;
        canvas.parentElement.querySelector('.activity-empty').hidden = populated;
        legend(key,chart);
    }

    function activityChart(dimension) {
        const key = 'activity-'+dimension;
        const measure = document.getElementById('activityMeasure-'+key).value;
        const tokens = measure.endsWith('tokens');
        const timeline = dimension === 'models' ? data.timeline : data.strategy_timeline;
        draw(key, {
            type:'bar', data:{labels:[...timeline.labels,labels.total],datasets:timeline.series.map(series => ({
                profile:series.id,label:series.label,data:[...series[measure],series[measure].reduce((sum,number)=>sum+number,0)],
                backgroundColor:displayColor(series.color),borderRadius:2,maxBarThickness:42
            }))},
            options:{interaction:{mode:'index',intersect:false},scales:{
                x:{stacked:true,grid:{display:false},ticks:{maxTicksLimit:8}},
                y:{stacked:true,beginAtZero:true,ticks:{callback:number=>measure==='cost'?'$'+formatter.format(number):tokens?compact.format(number):formatter.format(number)}}},
                plugins:{tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${value(context.parsed.y,tokens?0:measure==='cost'?3:0)}`}}}}
        });
    }

    function comparisonCharts(dimension) {
        const groups = data[dimension];
        const fieldForGroup = dimension === 'models' ? 'profile' : 'policy';
        const outline = palette().surface;
        for (const [metric,xLabel] of [['cost',labels.cost],['time',labels.seconds],['content',labels.content]]) {
            const field = metric === 'time' ? 'seconds' : metric;
            draw(metric+'-'+dimension,{
                type:'scatter',data:{datasets:groups.map(group=>({
                    profile:group.id,label:group.label,backgroundColor:displayColor(group.color),
                    // Chart.js draws lower-order datasets last, above coincident points.
                    order:group.id==='P5'?-1:0,clip:8,
                    borderColor:group.id==='P5'?outline:displayColor(group.color),
                    pointBorderWidth:group.id==='P5'?1.5:1,
                    pointStyle:'circle',pointRadius:group.id==='P5'?5.5:4,pointHoverRadius:7,
                    data:data.points.filter(point=>point[fieldForGroup]===group.id && point[field]!=null)
                        .map(point=>({...point,x:point[field],y:point.removed}))
                }))},
                options:{layout:{padding:{right:10}},scales:{x:{title:{display:true,text:xLabel},beginAtZero:true,max:metric==='content'?100:undefined},
                    y:{title:{display:true,text:labels.removed}}},
                    plugins:{attractiveQuadrant:{enabled:true,highX:metric==='content'},tooltip:{callbacks:{
                        label:context=>`${context.dataset.label} · #${context.raw.id}: ${value(context.raw.y)} · ${value(context.raw.x,metric==='cost'?4:1)}`
                    }}},onClick:(_,elements,chart)=>{
                        if (elements.length) {
                            const {datasetIndex,index}=elements[0];
                            const point=chart.data.datasets[datasetIndex].data[index];
                            window.location.assign('/remediation/'+point.id);
                        }
                    }}
            });
        }
        draw('iterations-'+dimension,{
            type:'scatter',data:{labels:groups.map(group=>group.label),datasets:groups.map(group=>({
                profile:group.id,label:group.label,backgroundColor:displayColor(group.color),
                pointStyle:'circle',pointRadius:5,pointHoverRadius:7,
                data:[{x:group.label,y:group.iterations}]
            }))},options:{scales:{
                x:{type:'category',offset:true,ticks:{autoSkip:false,maxRotation:0,callback:position=>axisLabel(groups[position]?.label||'')},title:{display:true,text:dimension==='models'?labels.model:labels.strategy},grid:{display:false}},
                y:{beginAtZero:true,title:{display:true,text:labels.iterationsTotal}}},
                plugins:{tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${value(context.raw.y,0)}`}}}}
        });
    }

    function axisLabel(label) {
        const lines = [''];
        for (const word of label.split(' ')) {
            const current = lines.at(-1);
            if (current && current.length+word.length+1 > 8) lines.push(word);
            else lines[lines.length-1] = current ? current+' '+word : word;
        }
        return lines;
    }

    function plot() {
        if (typeof Chart === 'undefined') return;
        Chart.defaults.font.family=getComputedStyle(document.documentElement).getPropertyValue('--ui-font').trim() || 'monospace';
        for (const dimension of ['models','strategies']) {
            activityChart(dimension);
            comparisonCharts(dimension);
        }
    }

    function render() {
        if (!data.totals) return;
        cards();rankings();plot();
        status.textContent = `${data.totals.active ? labels.live : labels.updated} · ${data.updated.slice(11,19)}`;
        status.classList.toggle('is-live',data.totals.active>0);
    }

    function schedule() {
        clearTimeout(timer);
        if (!disposed && !document.hidden) timer=setTimeout(load,data.totals?.active ? 15000 : 60000);
    }

    async function load() {
        clearTimeout(timer);
        controller?.abort();controller=new AbortController();
        const mine=++revision;
        const query=new URLSearchParams(new FormData(form));
        const endpoint=new URL(panel.dataset.endpoint,window.location.href);
        endpoint.search=query.toString();
        try {
            const response=await fetch(endpoint,{signal:controller.signal,cache:'no-store'});
            if (!response.ok) throw Error('Dashboard request failed');
            const next=await response.json();
            if (mine!==revision || disposed) return;
            data=next;render();message.textContent='';
            const url=new URL(form.action,window.location.href);url.search=query.toString();
            history.replaceState(null,'',url.pathname+url.search);
        } catch(error) {
            if (error.name!=='AbortError' && mine===revision) message.textContent=labels.error;
        } finally {
            if (mine===revision) schedule();
        }
    }
    form.addEventListener('submit',event=>{event.preventDefault();load();});
    form.addEventListener('change',load);
    panel.querySelectorAll('[data-activity-measure]').forEach(select=>select.addEventListener('change',plot));
    document.addEventListener('visibilitychange',()=>{
        if (document.hidden) {clearTimeout(timer);controller?.abort();}
        else load();
    });
    new MutationObserver(()=>plot()).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    window.addEventListener('pagehide',()=>{disposed=true;clearTimeout(timer);controller?.abort();charts.forEach(chart=>chart.destroy());},{once:true});
    render();schedule();
})();
