/* Scatter styling only: leave observations, scales and tooltip behavior intact. */
(() => {
  const colors = {
    axeLighthouseChart: '#18529d',
    criticalLighthouseChart: '#b91c1c',
    runtimeChart: '#28ad56',
    domAxeChart: '#7654a3',
    aimLighthouseChart: '#0891b2',
    aimAxeChart: '#b76a12',
  };
  const borders = {
    axeLighthouseChart: '#103b72',
    criticalLighthouseChart: '#7f1d1d',
    runtimeChart: '#187a3d',
    domAxeChart: '#503672',
    aimLighthouseChart: '#0e7490',
    aimAxeChart: '#7e470b',
  };
  window.warpScatterVisuals = {
    id: 'warpScatterVisuals',
    beforeUpdate(chart) {
      chart.data.datasets.forEach(dataset => {
        if ((dataset.type || chart.config.type) !== 'scatter') return;
        const color = colors[chart.canvas.id] || dataset.backgroundColor;
        const border = borders[chart.canvas.id] || dataset.borderColor || color;
        dataset.backgroundColor = dataset.pointBackgroundColor = color;
        dataset.borderColor = dataset.pointBorderColor = border;
        dataset.pointBorderWidth = 1;
        dataset.pointHoverBackgroundColor = color;
        dataset.pointHoverBorderColor = border;
        dataset.pointHoverBorderWidth = 1;
      });
    },
  };
})();
