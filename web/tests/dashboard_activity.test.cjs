const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../app/static/js/dashboard_activity.js'),'utf8');

function fixture(dynamicOnly=false,trends={}) {
    function element(id='') {
        return {id,style:{},dataset:{},children:[],events:{},attributes:{},hidden:false,
            classList:{toggle(){}},append(...items){this.children.push(...items)},
            replaceChildren(...items){this.children=items},setAttribute(key,value){this.attributes[key]=value},
            toggleAttribute(key,on){if(key==='hidden')this.hidden=on},
            addEventListener(key,fn){this.events[key]=fn}};
    }
    const model={id:'luna:low',label:'Luna light',color:'#215F97',iterations:2};
    const sol={id:'sol:low',label:'Sol light',color:'#218A79',iterations:3};
    const p1={id:'P1',policy:'P1',label:'P1',color:'#215F97',iterations:5};
    const p5={id:'P5',policy:'P5',label:'P5',color:'#C13C83',iterations:4};
    const series=(group,cost,tokens)=>({...group,cost:[cost],runs:[1],iterations:[group.iterations],tokens:[tokens]});
    const board={totals:{active:0},trends,updated:'2026-10-19T12:00:00',
        models:dynamicOnly?[]:[model,sol],strategies:dynamicOnly?[p5]:[p1,p5],
        timeline:{labels:['2026-10-19'],series:dynamicOnly?[]:[series(model,.1,10),series(sol,.2,20)]},
        strategy_timeline:{labels:['2026-10-19'],series:dynamicOnly?[series(p5,.3,30)]:[series(p1,.3,30),series(p5,.3,30)]},
        points:[{id:1,profile:model.id,policy:'P1',removed:2,cost:.1,seconds:10,content:100},
                {id:2,profile:sol.id,policy:'P1',removed:3,cost:.2,seconds:20,content:100},
                {id:3,profile:null,policy:'P5',removed:4,cost:.3,seconds:30,content:100}]};
    const elements=new Map();
    const get=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id)};
    const legends=new Map();
    const panel=get('dashboardActivity');
    const selects=['models','strategies'].map(d=>{const e=get('activityMeasure-activity-'+d);e.value='cost';return e});
    const metrics=new Map(Object.keys(trends).map(key=>{
        const card=element();card.dataset.dashboardMetric=key;
        const nodes=new Map(['[data-metric-value]','[data-metric-detail]','[data-metric-sparkline]',
            '.metric-sparkline','[data-metric-trend-label]'].map(selector=>[selector,element()]));
        card.querySelector=selector=>nodes.get(selector);
        nodes.get('.metric-sparkline').querySelector=selector=>nodes.get(selector);
        return [key,card];
    }));
    panel.querySelectorAll=selector=>selector==='[data-activity-measure]'?selects:
        selector==='[data-dashboard-metric]'?[...metrics.values()]:[];
    panel.querySelector=selector=>{
        if(!legends.has(selector))legends.set(selector,element());
        return legends.get(selector);
    };
    get('dashboardActivityData').textContent=JSON.stringify(board);
    get('dashboardActivityLabels').textContent=JSON.stringify({total:'Total',model:'Model',strategy:'Strategy',iterationsTotal:'Evaluated iterations (total)'});
    const charts=new Map();
    class Chart {
        static defaults={font:{}};
        constructor(canvas,config){this.data=config.data;this.options=config.options;this.visible=new Map();charts.set(canvas.id,this)}
        setDatasetVisibility(i,shown){this.visible.set(i,shown)}
        isDatasetVisible(i){return this.visible.get(i)!==false}
        update(){}
        destroy(){}
    }
    const document={documentElement:{lang:'en',dataset:{theme:'dark'}},hidden:false,
        getElementById(id){const node=get(id);if(id.startsWith('dashboardChart-'))node.parentElement={querySelector:()=>get(id+'-empty')};return node},
        createElement:()=>element(),createTextNode:text=>text,addEventListener(){}};
    let themeChanged;
    const env={document,Chart,Intl,Map,Number,JSON,console,
        getComputedStyle:()=>({getPropertyValue:()=>''}),
        MutationObserver:class{constructor(fn){themeChanged=fn}observe(){}},
        window:{addEventListener(){},location:{}},setTimeout:()=>1,clearTimeout(){}};
    vm.runInNewContext(source,env);
    return {charts,get,legends,selects,document,themeChanged,metrics};
}

test('metric trends stay flat through inactive periods and resume at the next observation',()=>{
    const f=fixture(false,{evaluation_axe:[null,10,null,null,20,null]});
    const card=f.metrics.get('evaluation_axe');
    const graphic=card.querySelector('.metric-sparkline');
    const path=card.querySelector('[data-metric-sparkline]').attributes.d;
    const points=[...path.matchAll(/[ML]([\d.]+),([\d.]+)/g)].map(match=>[+match[1],+match[2]]);
    assert.equal((path.match(/M/g)||[]).length,1,'the line has no disconnected segments');
    assert.equal(points.length,5,'leading unobserved periods remain outside the displayed series');
    assert.deepEqual(points.map(point=>point[1]),[43,43,43,5,5]);
    assert.equal(points.at(-1)[0],157,'the last observation continues to the end of the card');
    assert.equal(graphic.hidden,false);
    assert.equal(graphic.dataset.trend,'worsening');
});

test('a single observed value stays flat and wholly unavailable trends remain hidden',()=>{
    const f=fixture(false,{axe:[null,4,null,null],evaluation_axe:[null,null],
        evaluation_lighthouse:[90],runs:[0,0,0]});
    for(const key of ['axe','evaluation_lighthouse','runs']) {
        const card=f.metrics.get(key);
        assert.equal(card.querySelector('.metric-sparkline').hidden,false);
        const points=[...card.querySelector('[data-metric-sparkline]').attributes.d.matchAll(/[ML]([\d.]+),([\d.]+)/g)];
        assert.ok(points.length>=2);
        assert.ok(points.every(point=>point[2]===points[0][2]));
    }
    assert.equal(f.metrics.get('axe').querySelector('.metric-sparkline').dataset.trend,'unchanged');
    const missing=f.metrics.get('evaluation_axe');
    assert.equal(missing.querySelector('.metric-sparkline').hidden,true);
    assert.equal(missing.querySelector('[data-metric-sparkline]').attributes.d,'');
});

test('ten charts keep models and strategies separate, including their resource totals',()=>{
    const f=fixture();
    assert.equal(f.charts.size,10);
    for(const metric of ['activity','cost','time','content','iterations']) {
        const models=f.charts.get('dashboardChart-'+metric+'-models');
        const strategies=f.charts.get('dashboardChart-'+metric+'-strategies');
        assert.deepEqual(Array.from(models.data.datasets,d=>d.label),['Luna light','Sol light']);
        assert.deepEqual(Array.from(strategies.data.datasets,d=>d.label),['P1','P5']);
        if(['cost','time','content'].includes(metric)) {
            assert.equal(models.data.datasets.flatMap(d=>d.data).some(p=>p.id===3),false);
            assert.equal(strategies.data.datasets[1].data[0].id,3);
        }
    }
    assert.equal(f.charts.get('dashboardChart-iterations-models').options.scales.x.title.text,'Model');
    const iterations=f.charts.get('dashboardChart-iterations-models');
    assert.equal(iterations.options.scales.x.type,'category');
    assert.equal(iterations.options.scales.x.ticks.autoSkip,false);
    assert.deepEqual(Array.from(iterations.data.labels),['Luna light','Sol light']);
    assert.equal(iterations.data.datasets[0].data[0].x,'Luna light');
    assert.equal(iterations.data.datasets.at(-1).data[0].x,'Sol light');
    assert.equal(f.charts.get('dashboardChart-iterations-strategies').options.scales.x.title.text,'Strategy');
    assert.equal(f.charts.get('dashboardChart-activity-strategies').data.datasets[1].data.at(-1),.3);
    assert.notEqual(f.charts.get('dashboardChart-cost-strategies').data.datasets[1].backgroundColor,
                    f.charts.get('dashboardChart-cost-models').data.datasets[1].backgroundColor);
});

test('activity controls and legend visibility remain independent through redraws and theme changes',()=>{
    const f=fixture();
    const key='[data-chart-legend="cost-strategies"]';
    f.legends.get(key).children[1].events.click();
    f.selects[0].value='tokens';f.selects[0].events.change();
    assert.equal(f.charts.get('dashboardChart-activity-models').data.datasets[0].data.at(-1),10);
    assert.equal(f.charts.get('dashboardChart-activity-strategies').data.datasets[0].data.at(-1),.3);
    assert.equal(f.charts.get('dashboardChart-cost-strategies').isDatasetVisible(1),false);
    assert.equal(f.charts.get('dashboardChart-content-strategies').isDatasetVisible(1),true);
    f.document.documentElement.dataset.theme='light';f.themeChanged();
    assert.equal(f.charts.get('dashboardChart-cost-strategies').data.datasets[1].backgroundColor,'#C13C83');
    assert.equal(f.charts.get('dashboardChart-cost-strategies').isDatasetVisible(1),false);
});

test('a P5-only filter shows empty model charts without hiding the strategy observations',()=>{
    const f=fixture(true);
    for(const metric of ['activity','cost','time','content','iterations']) {
        assert.equal(f.get('dashboardChart-'+metric+'-models').hidden,true);
        assert.equal(f.get('dashboardChart-'+metric+'-strategies').hidden,false);
    }
});

test('P5 draws above coincident points and remains complete at 100 percent retention',()=>{
    const f=fixture();
    for(const metric of ['cost','time','content']) {
        const chart=f.charts.get('dashboardChart-'+metric+'-strategies');
        const [fixed,p5]=chart.data.datasets;
        assert.ok(p5.order<fixed.order, 'lower Chart.js order draws P5 last');
        assert.ok(p5.pointRadius>fixed.pointRadius);
        assert.ok(p5.clip>=p5.pointRadius+p5.pointBorderWidth);
        assert.ok(chart.options.layout.padding.right>=p5.clip);
        assert.equal(p5.pointStyle,'circle');
    }
    const content=f.charts.get('dashboardChart-content-strategies');
    assert.equal(content.options.scales.x.max,100);
    assert.equal(content.data.datasets[1].data[0].x,100);
    assert.equal(content.data.datasets[1].data[0].y,4);
});
