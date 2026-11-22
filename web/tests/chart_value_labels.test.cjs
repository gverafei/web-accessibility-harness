const {test} = require('node:test');
const assert = require('node:assert/strict');
const plugin = require('../app/static/js/chart_value_labels.js');
function draw(values, {horizontal=false, stacked=false, thickness=70, type='bar', custom=false, dark=false, spacing=90}={}) {
    global.document = {documentElement:{lang:'en',getAttribute:()=>dark?'dark':'light'}};
    const labels=[], backgrounds=[];
    const chart={config:{plugins:custom?[{id:'commonErrorValueLabels'}]:[]},
        chartArea:{left:0,right:500,top:0,bottom:300},
        data:{datasets:[{data:values}]},isDatasetVisible:()=>true,
        getDatasetMeta:()=>({type,vScale:{options:{stacked}},data:values.map((_,i)=>({horizontal,
            x:horizontal?180:i*spacing+50,y:horizontal?i*spacing+30:70,base:horizontal?0:280,
            width:thickness,height:horizontal?thickness:210}))}),
        ctx:{save(){},restore(){},measureText:t=>({width:t.length*7}),
            fillRect(){backgrounds.push(this.fillStyle)},fillText(t,x,y){labels.push({t,x,y,color:this.fillStyle})}}};
    plugin.afterDatasetsDraw(chart);
    return {labels,backgrounds};
}
test('numeric values including zero and negatives, but not null or ranges',()=>{
    assert.deepEqual(draw([0,28.184,-4,null,[2,5]]).labels.map(x=>x.t),['0','28.18','-4']);
});
test('horizontal and stacked values',()=>{
    assert.equal(draw([12],{horizontal:true}).labels.length,1);
    assert.equal(draw([12],{stacked:true}).labels[0].y,175);
    assert.equal(draw([0],{stacked:true}).labels.length,0);
});
test('dense bars, nonbars, and already labelled charts stay unchanged',()=>{
    for(const options of [{thickness:8},{type:'scatter'},{custom:true}])
        assert.equal(draw([12],options).labels.length,0);
});
test('dark labels have an opaque contrasting background',()=>{
    const result=draw([12],{dark:true});
    assert.equal(result.labels[0].color,'#f1f5f9');
    assert.deepEqual(result.backgrounds,['#17212b']);
});
test('light labels have no white rectangle over the bar',()=>{
    const result=draw([14],{horizontal:true,stacked:true});
    assert.equal(result.labels[0].color,'#17212b');
    assert.deepEqual(result.backgrounds,[]);
});
test('close horizontal labels do not collide',()=>{
    assert.equal(draw([12,13],{horizontal:true,spacing:2}).labels.length,1);
    // Oversized text boxes never escape the plotting area.
    assert.equal(draw([1e100]).labels.length,0);
});
test('ordinary narrow bars show labels in available category space',()=>{
    assert.deepEqual(draw([28.18,40.13,34.40,37.77,45.35],{thickness:32,spacing:90}).labels.map(x=>x.t),
        ['28.18','40.13','34.4','37.77','45.35']);
    assert.equal(draw([28.18],{thickness:32,stacked:true}).labels.length,0);
    assert.equal(draw([28.18,40.13],{thickness:32,spacing:20}).labels.length,1);
});
