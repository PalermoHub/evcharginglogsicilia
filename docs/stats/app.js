const summaryBox = document.getElementById('summary-box');
const heroLead = document.getElementById('hero-lead');
const poiUsageNote = document.getElementById('poi-usage-note');
const poiUsageTable = document.getElementById('poi-usage-table');
const operatorsUsageNote = document.getElementById('operators-usage-note');
const operatorsUsageTable = document.getElementById('operators-usage-table');

// Palette derivata dall'immagine hero (vedi ../theme.css) — stessa
// convenzione duplicata in ogni script che disegna grafici (docs/app.js,
// shared-drilldown.js): ECharts non legge le CSS custom properties.
const HERO_GREEN = '#1da542';
const ACCENT = '#28a1bd';
const STATUS_RED = '#b02a2a';

const CATEGORY_LABELS = {
  musei: 'Musei',
  supermercati: 'Supermercati',
  banche: 'Banche',
  ospedali: 'Ospedali',
  ambulatori: 'Ambulatori',
  svincoli_autostradali: 'Svincoli autostradali',
  incroci_primarie: 'Incroci di strade primarie',
};

let statsPayload = null;
let usageTimeseriesRows = [];
let raccoltaDalIso = null;

// --- Summary (stats.json) ------------------------------------------------

// Giorni di calendario coperti dalla raccolta, dalla prima rilevazione
// assoluta (raccolta_dati_dal) all'ultimo snapshot (generated_at):
// entrambe le date sono normalizzate a mezzanotte locale prima della
// differenza, altrimenti l'orario del primo/ultimo snapshot del giorno
// falserebbe il conteggio di un giorno in più o in meno.
function daysCollected(fromIso, toIso) {
  const from = new Date(`${fromIso.split('T')[0]}T00:00:00`);
  const to = new Date(`${toIso.split('T')[0]}T00:00:00`);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
  return Math.round((to - from) / 86400000) + 1;
}

function renderSummaryCards(data) {
  const raccoltaDalLabel = window.EVFormat
    ? EVFormat.popupDate(data.summary.raccolta_dati_dal.split('T')[0])
    : data.summary.raccolta_dati_dal;
  const totaleGiorni = daysCollected(data.summary.raccolta_dati_dal, data.summary.generated_at);
  summaryBox.innerHTML = `
    <div class="mb-2"><strong>Totale:</strong> ${data.summary.total}</div>
    <div class="mb-2"><strong>Quota attive:</strong> ${data.summary.share_active}% (di cui ${data.summary.active_unknown} stimate: l'operatore non distingue occupata da libera)</div>
    <div class="mb-2"><strong>Ultimo snapshot:</strong> ${window.EVFormat ? EVFormat.dateTime(data.summary.generated_at) : data.summary.generated_at}</div>
    <div class="mb-2"><strong>Dati raccolti dal:</strong> ${raccoltaDalLabel}</div>
    ${totaleGiorni != null ? `<div class="mb-2">Per un totale di <strong>${totaleGiorni}</strong> giorni</div>` : ''}
  `;

  if (heroLead) {
    heroLead.textContent = `L'applicazione archivia i dati dal ${raccoltaDalLabel} e pubblica questo report giornaliero.`;
  }
}

// --- Andamento conteggio giornaliero (trends.json) -----------------------

function trendMessage(block) {
  return `Raccolta dati in corso: servono almeno ${block.days_needed} giorni di storico (oggi ${block.days_collected}).`;
}

function renderPlaceholder(containerId, block) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.classList.remove('echart-trend');
  el.innerHTML = `<div class="alert alert-light border small mb-0">${trendMessage(block)}</div>`;
}

function pointsInRange(points, from, to) {
  return points.filter((p) => (!from || p.date >= from) && (!to || p.date <= to));
}

let countBlockRaw = null;
let countChart = null;

function renderCountDailyPoints(points) {
  const el = document.getElementById('chart-count-daily');
  if (!el || typeof echarts === 'undefined') return;
  if (!countChart) countChart = echarts.init(el, 'evtrento-dark');
  countChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Attive', 'Non attive'] },
    grid: { left: 40, right: 20, top: 40, bottom: 40 },
    xAxis: {
      type: 'category',
      data: points.map((p) => (window.EVFormat ? EVFormat.dateShort(p.date) : p.date)),
      axisLabel: { rotate: 0, fontSize: 10 },
    },
    yAxis: { type: 'value' },
    series: [
      { name: 'Attive', type: 'bar', stack: 'totale', barCategoryGap: '10%', itemStyle: { color: HERO_GREEN }, data: points.map((p) => p.n_attive) },
      { name: 'Non attive', type: 'bar', stack: 'totale', barCategoryGap: '10%', itemStyle: { color: STATUS_RED }, data: points.map((p) => p.n_non_attive) },
    ],
  });
  if (window.EVChartTools) EVChartTools.attach(countChart, el, { filename: 'colonnine-attive-non-attive' });
}

function applyCountFilter() {
  if (!countBlockRaw) return;
  const from = document.getElementById('count-date-from')?.value || '';
  const to = document.getElementById('count-date-to')?.value || '';
  renderCountDailyPoints(pointsInRange(countBlockRaw.points, from, to));
}

function renderCountSection(block) {
  if (!block.available) return renderPlaceholder('chart-count-daily', block);
  countBlockRaw = block;
  applyCountFilter();
  window.addEventListener('resize', () => countChart && countChart.resize());
  const fromInput = document.getElementById('count-date-from');
  const toInput = document.getElementById('count-date-to');
  [fromInput, toInput].forEach((input) => input && input.addEventListener('change', applyCountFilter));
}

let monitorabiliBlockRaw = null;
let monitorabiliChart = null;

function renderMonitorabiliPoints(points) {
  const el = document.getElementById('chart-monitorabili-daily');
  if (!el || typeof echarts === 'undefined') return;
  if (!monitorabiliChart) monitorabiliChart = echarts.init(el, 'evtrento-dark');
  monitorabiliChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 20, bottom: 60 },
    xAxis: {
      type: 'category',
      data: points.map((p) => (window.EVFormat ? EVFormat.dateOnly(p.date) : p.date)),
      axisLabel: { rotate: 45, fontSize: 10 },
    },
    yAxis: { type: 'value' },
    series: [{ name: 'Colonnine monitorabili', type: 'line', smooth: true, itemStyle: { color: ACCENT }, data: points.map((p) => p.n_monitorabili) }],
  });
  if (window.EVChartTools) EVChartTools.attach(monitorabiliChart, el, { filename: 'colonnine-monitorabili' });
}

function applyMonitorabiliFilter() {
  if (!monitorabiliBlockRaw) return;
  const from = document.getElementById('monitorabili-date-from')?.value || '';
  const to = document.getElementById('monitorabili-date-to')?.value || '';
  renderMonitorabiliPoints(pointsInRange(monitorabiliBlockRaw.points, from, to));
}

function renderMonitorabiliSection(block) {
  if (!block.available) return renderPlaceholder('chart-monitorabili-daily', block);
  monitorabiliBlockRaw = block;
  applyMonitorabiliFilter();
  window.addEventListener('resize', () => monitorabiliChart && monitorabiliChart.resize());
  const fromInput = document.getElementById('monitorabili-date-from');
  const toInput = document.getElementById('monitorabili-date-to');
  [fromInput, toInput].forEach((input) => input && input.addEventListener('change', applyMonitorabiliFilter));
}

// --- Filtri condivisi (potenza / operatore / POI) -------------------------

const usageFilters = { tier: 'tutte', operator: '', poiCategory: '' };
let granularity = 'giorno';

function filterRows(rows) {
  return rows.filter((r) => {
    if (usageFilters.tier !== 'tutte' && r.fascia_potenza !== usageFilters.tier) return false;
    if (usageFilters.operator && r.cpo !== usageFilters.operator) return false;
    if (usageFilters.poiCategory && !r.poi_categorie.includes(usageFilters.poiCategory)) return false;
    return true;
  });
}

function populateFilterOptions(rows) {
  const operatorSelect = document.getElementById('usage-operator-filter');
  const poiSelect = document.getElementById('usage-poi-filter');
  if (operatorSelect) {
    const operators = Array.from(new Set(rows.map((r) => r.cpo))).sort((a, b) => a.localeCompare(b, 'it'));
    operatorSelect.innerHTML = '<option value="">Tutti</option>' + operators.map((o) => `<option value="${o}">${o}</option>`).join('');
  }
  if (poiSelect) {
    poiSelect.innerHTML = '<option value="">Ovunque</option>' + Object.entries(CATEGORY_LABELS)
      .map(([key, label]) => `<option value="${key}">${label}</option>`)
      .join('');
  }
}

function wireUsageFilters() {
  const buttons = Array.from(document.querySelectorAll('#usage-power-filter button'));
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      usageFilters.tier = btn.dataset.tier;
      refreshUsageViews();
    });
  });

  const operatorSelect = document.getElementById('usage-operator-filter');
  operatorSelect?.addEventListener('change', () => {
    usageFilters.operator = operatorSelect.value;
    refreshUsageViews();
  });

  const poiSelect = document.getElementById('usage-poi-filter');
  poiSelect?.addEventListener('change', () => {
    usageFilters.poiCategory = poiSelect.value;
    refreshUsageViews();
  });

  const granButtons = Array.from(document.querySelectorAll('#granularity-filter button'));
  granButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      granButtons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      granularity = btn.dataset.gran;
      renderGranularityCharts(filterRows(usageTimeseriesRows));
    });
  });
}

function refreshUsageViews() {
  const filtered = filterRows(usageTimeseriesRows);
  renderKpiCards(filtered);
  renderGranularityCharts(filtered);
  renderPoiUsageTable(lastPoiUsagePayload, usageFilters.tier);
}

// --- KPI ricariche ---------------------------------------------------------

function renderKpiCards(rows) {
  const container = document.getElementById('usage-kpi-cards');
  if (!container) return;
  const kwh = rows.reduce((sum, r) => sum + (r.kwh_stimato || 0), 0);
  const sessioni = rows.reduce((sum, r) => sum + (r.n_sessioni || 0), 0);
  const durataTotale = rows.reduce((sum, r) => sum + (r.durata_totale_minuti || 0), 0);

  const now = Date.now();
  const start = raccoltaDalIso ? new Date(raccoltaDalIso).getTime() : now;
  const oreTrascorse = Math.max(1, (now - start) / 3600000);
  const giorniTrascorsi = Math.max(1, oreTrascorse / 24);
  const settimaneTrascorse = Math.max(1, giorniTrascorsi / 7);

  const durataMediaRicarica = sessioni > 0 ? durataTotale / sessioni : null;

  const rateCard = (label, unit, totale, tono) => `
    <div class="col-lg-4">
      <div class="card stat-card border-0 shadow-sm bg-${tono} bg-gradient text-white h-100">
        <div class="card-body">
          <div class="small text-white-50 mb-1">${label}</div>
          <div class="small text-white-50">Oraria: <strong class="text-white">${(totale / oreTrascorse).toFixed(2)} ${unit}</strong></div>
          <div class="small text-white-50">Giornaliera: <strong class="text-white">${(totale / giorniTrascorsi).toFixed(2)} ${unit}</strong></div>
          <div class="small text-white-50">Settimanale: <strong class="text-white">${(totale / settimaneTrascorse).toFixed(2)} ${unit}</strong></div>
        </div>
      </div>
    </div>`;

  container.innerHTML = [
    rateCard('Energia erogata (media)', 'kWh', kwh, 'success'),
    rateCard('Ricariche (media)', 'ricariche', sessioni, 'info'),
    `<div class="col-lg-4">
      <div class="card stat-card border-0 shadow-sm bg-secondary bg-gradient text-white h-100">
        <div class="card-body">
          <div class="small text-white-50 mb-1">Durata media di una ricarica</div>
          <div class="display-6 fw-semibold">${durataMediaRicarica != null ? durataMediaRicarica.toFixed(0) : '—'}</div>
          <div class="small text-white-50">minuti (${sessioni} ricariche osservate, sui filtri applicati)</div>
        </div>
      </div>
    </div>`,
  ].join('');
}

// --- Serie storiche con granularità ----------------------------------------

function isoWeekKey(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
}

function periodKey(dateStr, gran) {
  if (gran === 'settimana') return isoWeekKey(dateStr);
  if (gran === 'mese') return dateStr.slice(0, 7);
  return dateStr;
}

function periodLabel(key, gran) {
  if (!window.EVFormat) return key;
  if (gran === 'giorno') return EVFormat.dateOnly(key);
  if (gran === 'mese') return EVFormat.monthYear(key);
  return key; // settimana: "2026-W32" resta leggibile così com'è
}

let colonnineChart = null;
let kwhChart = null;

function aggregateHourly(rows) {
  const perHourStations = Array(24).fill(0);
  const perHourKwh = Array(24).fill(0);
  const days = new Set();
  rows.forEach((r) => {
    days.add(r.date);
    const oreAttive = r.ore_charging.reduce((a, b) => a + b, 0);
    // Il dataset non registra l'energia per singola ora, solo il totale
    // della giornata: distribuirla in parti uguali sulle ore in cui la
    // colonnina risulta in carica è una stima ulteriore (coerente con le
    // altre stime del sito), non una lettura reale.
    const kwhPerOraAttiva = oreAttive > 0 && r.kwh_stimato ? r.kwh_stimato / oreAttive : 0;
    r.ore_charging.forEach((flag, h) => {
      if (!flag) return;
      perHourStations[h] += 1;
      perHourKwh[h] += kwhPerOraAttiva;
    });
  });
  const nDays = days.size || 1;
  return {
    labels: Array.from({ length: 24 }, (_, h) => `${h}:00`),
    stazioni: perHourStations.map((v) => v / nDays),
    kwh: perHourKwh.map((v) => v / nDays),
  };
}

function aggregateByPeriod(rows, gran) {
  const buckets = new Map();
  rows.forEach((r) => {
    const key = periodKey(r.date, gran);
    const b = buckets.get(key) || { stazioni: new Set(), kwh: 0 };
    b.stazioni.add(r.id_evse);
    b.kwh += r.kwh_stimato || 0;
    buckets.set(key, b);
  });
  const keys = Array.from(buckets.keys()).sort();
  return {
    labels: keys.map((k) => periodLabel(k, gran)),
    stazioni: keys.map((k) => buckets.get(k).stazioni.size),
    kwh: keys.map((k) => Math.round(buckets.get(k).kwh * 100) / 100),
  };
}

function renderGranularityCharts(rows) {
  const data = granularity === 'ora' ? aggregateHourly(rows) : aggregateByPeriod(rows, granularity);

  const colEl = document.getElementById('chart-colonnine-in-uso');
  if (colEl && typeof echarts !== 'undefined') {
    if (!colonnineChart) colonnineChart = echarts.init(colEl, 'evtrento-dark');
    colonnineChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 40, bottom: 60 },
      xAxis: { type: 'category', data: data.labels, axisLabel: { rotate: granularity === 'ora' ? 0 : 45, fontSize: 10 } },
      yAxis: { type: 'value' },
      series: [{ name: 'Colonnine in uso', type: 'bar', itemStyle: { color: ACCENT }, data: data.stazioni }],
    });
    if (window.EVChartTools) EVChartTools.attach(colonnineChart, colEl, { filename: 'colonnine-in-uso' });
  }

  const kwhEl = document.getElementById('chart-kwh-erogati');
  if (kwhEl && typeof echarts !== 'undefined') {
    if (!kwhChart) kwhChart = echarts.init(kwhEl, 'evtrento-dark');
    kwhChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 20, bottom: 60 },
      xAxis: { type: 'category', data: data.labels, axisLabel: { rotate: granularity === 'ora' ? 0 : 45, fontSize: 10 } },
      yAxis: { type: 'value', name: 'kWh' },
      series: [{ name: 'kWh erogati', type: 'line', smooth: true, itemStyle: { color: HERO_GREEN }, data: data.kwh }],
    });
    if (window.EVChartTools) EVChartTools.attach(kwhChart, kwhEl, { filename: 'kwh-erogati' });
  }

  window.addEventListener('resize', () => {
    colonnineChart && colonnineChart.resize();
    kwhChart && kwhChart.resize();
  });
}

// --- POI / Luoghi (poi_usage.json) -----------------------------------------

let lastPoiUsagePayload = null;

function renderPoiUsageTable(data, tier = 'tutte') {
  if (!poiUsageTable) return;
  lastPoiUsagePayload = data;
  if (!data || !data.pois || data.pois.length === 0) {
    poiUsageNote.textContent = '';
    poiUsageTable.innerHTML = '<p class="text-muted mb-0">Dati non ancora disponibili: esegui fetch_poi.py, generate_station_usage.py e generate_poi_usage.py.</p>';
    return;
  }
  poiUsageNote.textContent = `Colonnine monitorabili entro ${data.soglia_metri} m da ciascun POI, e quante fra queste sono state effettivamente usate (almeno una ricarica osservata). Fonte POI: ${data.fonte_poi}.`;

  const rows = data.pois
    .map((p) => ({ ...p, usate_shown: tier === 'tutte' ? p.n_colonnine_usate : p.n_usate_by_power[tier] || 0 }))
    .sort((a, b) => b.usate_shown - a.usate_shown || a.name.localeCompare(b.name, 'it'));

  poiUsageTable.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle" id="poi-usage-table-el">
        <thead><tr><th>POI</th><th>Categoria</th><th>Entro soglia</th><th>Usate</th><th>Esempio</th></tr></thead>
        <tbody>
          ${rows
            .map(
              (r) => `
                <tr>
                  <td>${r.name}</td>
                  <td>${r.categoria_label}</td>
                  <td data-sort-value="${r.n_colonnine_entro_soglia}">${r.n_colonnine_entro_soglia}</td>
                  <td data-sort-value="${r.usate_shown}">${r.usate_shown}</td>
                  <td class="small text-muted">${r.esempio ? `${r.esempio.colonnina_indirizzo} (${r.esempio.distanza_m} m)` : '—'}</td>
                </tr>`
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
  enhanceTable(document.getElementById('poi-usage-table-el'));
}

// --- Operatori — ricariche (stations_usage.json) ---------------------------

function renderOperatorsUsageTable(city) {
  if (!operatorsUsageTable) return;
  const lista = (city && city.operatori_per_uso) || [];
  if (lista.length === 0) {
    operatorsUsageNote.textContent = '';
    operatorsUsageTable.innerHTML = '<p class="text-muted mb-0">Dati d\'uso non ancora disponibili.</p>';
    return;
  }
  const raccoltaDalLabel = raccoltaDalIso && window.EVFormat ? EVFormat.popupDate(raccoltaDalIso.split('T')[0]) : raccoltaDalIso;
  operatorsUsageNote.textContent = `Ricariche osservate dal ${raccoltaDalLabel} (${city.days_collected} giorni di storico raccolto finora).`;

  operatorsUsageTable.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle" id="operators-usage-table-el">
        <thead><tr><th>#</th><th>Operatore</th><th>N. ricariche</th><th>Media giornaliera</th></tr></thead>
        <tbody>
          ${lista
            .map(
              (op, i) => `
                <tr>
                  <td data-sort-value="${i + 1}">${i + 1}</td>
                  <td><span class="station-link" data-operator-popover="${op.cpo}">${op.cpo}</span></td>
                  <td data-sort-value="${op.n_sessioni}">${op.n_sessioni}</td>
                  <td data-sort-value="${op.media_sessioni_giornaliere ?? 0}">${op.media_sessioni_giornaliere ?? '—'}</td>
                </tr>`
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
  enhanceTable(document.getElementById('operators-usage-table-el'));
}

// --- Caricamento dati --------------------------------------------------

async function loadData() {
  const [statsResponse, trendsResponse, poiUsageResponse, usageTsResponse, usageResponse] = await Promise.all([
    fetch('data/stats.json'),
    fetch('data/trends.json').catch(() => null),
    fetch('data/poi_usage.json').catch(() => null),
    fetch('data/usage_timeseries.json').catch(() => null),
    fetch('../stations_usage.json').catch(() => null),
  ]);
  const payload = await statsResponse.json();
  statsPayload = payload;
  raccoltaDalIso = payload.summary.raccolta_dati_dal;
  renderSummaryCards(payload);

  if (trendsResponse && trendsResponse.ok) {
    const trends = await trendsResponse.json();
    renderCountSection(trends.andamento_conteggio_giornaliero);
    renderMonitorabiliSection(trends.colonnine_monitorabili_giornaliero);
  }

  if (usageTsResponse && usageTsResponse.ok) {
    const ts = await usageTsResponse.json();
    usageTimeseriesRows = ts.rows || [];
  }

  lastPoiUsagePayload = poiUsageResponse && poiUsageResponse.ok ? await poiUsageResponse.json() : null;

  populateFilterOptions(usageTimeseriesRows);
  wireUsageFilters();
  refreshUsageViews();

  if (usageResponse && usageResponse.ok) {
    const usage = await usageResponse.json();
    if (window.EVUsage) EVUsage.setData(usage);
    renderOperatorsUsageTable(usage.city);
  } else {
    renderOperatorsUsageTable(null);
  }
}

loadData();
