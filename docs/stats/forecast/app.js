const forecastNote = document.getElementById('forecast-note');

function unavailableMessage(block) {
  return `Servono almeno ${block.days_needed} giorni di storico per una previsione onesta (oggi ${block.days_collected}).`;
}

function renderForecast(block) {
  const meta = document.getElementById('forecast-meta-trento');
  const chartEl = document.getElementById('chart-forecast-trento');

  if (!block.available) {
    meta.textContent = '';
    chartEl.classList.remove('echart-trend');
    chartEl.innerHTML = `<div class="alert alert-light border small mb-0">${unavailableMessage(block)}</div>`;
    return;
  }

  meta.textContent = `Basata su ${block.days_collected} giorni di storico · errore tipico ±${block.mae_storico} punti percentuali.`;

  if (typeof echarts === 'undefined') return;
  const chart = echarts.init(chartEl, 'evtrento-dark');
  const labels = block.punti.map((p) => (window.EVFormat ? EVFormat.dateTime(p.ts) : p.ts.replace('T', ' ')));
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Stima', 'Intervallo'] },
    grid: { left: 40, right: 20, top: 40, bottom: 60 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        // banda min-max: prima un segmento invisibile fino al minimo, poi
        // impilato sopra un'area colorata larga (max - min) — il trucco
        // standard ECharts per disegnare un intervallo di confidenza.
        name: 'min',
        type: 'line',
        data: block.punti.map((p) => p.min),
        stack: 'range',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        tooltip: { show: false },
      },
      {
        name: 'Intervallo',
        type: 'line',
        data: block.punti.map((p) => Math.max(0, p.max - p.min)),
        stack: 'range',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'rgba(40, 161, 189, 0.18)' },
      },
      {
        name: 'Stima',
        type: 'line',
        data: block.punti.map((p) => p.share_charging),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#28a1bd', width: 2 },
      },
    ],
  });
  window.addEventListener('resize', () => chart.resize());
}

async function loadForecast() {
  const response = await fetch('../data/forecast.json');
  if (!response.ok) return;
  const payload = await response.json();
  forecastNote.textContent = payload.nota || '';
  renderForecast(payload);
}

loadForecast();
