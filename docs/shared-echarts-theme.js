// shared-echarts-theme.js — un tema ECharts registrato una sola volta,
// riusato da ogni echarts.init(el, 'evtrento-dark') nelle pagine con
// grafici (docs/app.js, docs/stats/app.js, docs/stats/forecast/app.js).
// Evita di dover impostare a mano axisLabel/splitLine/tooltip in ogni
// singola chiamata solo per renderli leggibili sul nuovo sfondo scuro.
if (typeof echarts !== 'undefined') {
  echarts.registerTheme('evtrento-dark', {
    backgroundColor: 'transparent',
    textStyle: { color: '#aeb9cc' },
    title: { textStyle: { color: '#ffffff' } },
    legend: { textStyle: { color: '#aeb9cc' } },
    tooltip: {
      backgroundColor: '#1c2540',
      borderColor: 'rgba(255,255,255,.12)',
      textStyle: { color: '#ffffff' },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: 'rgba(255,255,255,.2)' } },
      axisLabel: { color: '#aeb9cc' },
      axisTick: { lineStyle: { color: 'rgba(255,255,255,.2)' } },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisLabel: { color: '#aeb9cc' },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.08)' } },
    },
  });
}
