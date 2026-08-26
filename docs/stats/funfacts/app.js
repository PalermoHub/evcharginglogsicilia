const cardsContainer = document.getElementById('curiosities-cards');
const emptyState = document.getElementById('empty-state');
const daysNote = document.getElementById('days-note');

const tones = ['primary', 'success', 'info', 'warning', 'secondary', 'danger'];

let usoItemsAll = [];

function osmLink(lat, lon) {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}`;
}

function listItemHtml(rank, indirizzo, sottotitolo, lat, lon, idEvse) {
  const nomeAttr = idEvse ? ` data-station-popover="${idEvse}"` : '';
  return `
    <div class="list-group-item d-flex justify-content-between align-items-start gap-3">
      <div>
        <span class="badge bg-secondary me-2">#${rank}</span>
        <strong class="station-link"${nomeAttr}>${indirizzo}</strong>
        <div class="small text-muted">${sottotitolo}</div>
      </div>
      <a href="${osmLink(lat, lon)}" target="_blank" rel="noopener" class="small text-nowrap">Vedi su mappa ↗</a>
    </div>`;
}

function renderCuriosities(curiosita) {
  if (!curiosita || curiosita.length === 0) return false;
  cardsContainer.innerHTML = curiosita
    .map(
      (c, i) => `
      <div class="col-md-6">
        <div class="card shadow-sm h-100 border-0 border-start border-4 border-${tones[i % tones.length]}">
          <div class="card-body">
            <h2 class="h6 text-uppercase text-muted">${c.titolo}</h2>
            <p class="mb-0">${c.testo}</p>
          </div>
        </div>
      </div>`
    )
    .join('');
  return true;
}

function renderTop3Block(prefix, block) {
  const col = document.getElementById(`top3-${prefix}-col`);
  if (!block || !block.items || block.items.length === 0) return false;

  col.classList.remove('d-none');
  document.getElementById(`top3-${prefix}-title`).textContent = block.titolo;
  document.getElementById(`top3-${prefix}-desc`).textContent = block.descrizione || '';
  const list = document.getElementById(`top3-${prefix}-list`);
  list.innerHTML = block.items
    .map((item) => listItemHtml(item.rank, item.indirizzo, `${item.cpo} · ${item.valore}`, item.lat, item.lon, item.id_evse))
    .join('');
  if (window.EVUsage) EVUsage.wirePopovers(list);
  return true;
}

function renderUsoItems(tier) {
  const filtered = tier === 'tutte' ? usoItemsAll : usoItemsAll.filter((it) => it.fascia_potenza === tier);
  const top3 = filtered.slice(0, 3);
  const list = document.getElementById('top3-uso-list');
  list.innerHTML = top3.length
    ? top3.map((item, i) => listItemHtml(i + 1, item.indirizzo, `${item.cpo} · ${item.valore}`, item.lat, item.lon, item.id_evse)).join('')
    : '<div class="list-group-item text-muted small">Nessuna colonnina in questa fascia di potenza.</div>';
  if (window.EVUsage) EVUsage.wirePopovers(list);
}

function wireUsoFilter() {
  const buttons = Array.from(document.querySelectorAll('#uso-power-filter button'));
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      renderUsoItems(btn.dataset.tier);
    });
  });
}

function renderUsoBlock(block) {
  const col = document.getElementById('top3-uso-col');
  if (!block || !block.items || block.items.length === 0) return false;
  col.classList.remove('d-none');
  document.getElementById('top3-uso-title').textContent = block.titolo;
  document.getElementById('top3-uso-desc').textContent = block.descrizione || '';
  usoItemsAll = block.items;
  renderUsoItems('tutte');
  return true;
}

// Tabella completa degli operatori (per numero di colonnine), spostata qui
// da stats/app.js: sulla pagina Statistiche quel blocco duplicava
// concettualmente l'uso reale (già coperto dalla nuova tabella "Operatori —
// ricariche"), qui invece è coerente con le altre classifiche di curiosità.
const POWER_TIER_LABELS = { tutte: 'Colonnine', lenta: 'Colonnine ≤22 kW', rapida: 'Colonnine 22–50 kW', ultra: 'Colonnine >50 kW' };
let statsPayloadForOperators = null;

function renderOperatorsTable(data, tier = 'tutte') {
  const container = document.getElementById('operators-table');
  if (!container || !data) return;
  const countFor = (op) => (tier === 'tutte' ? op.count : op.by_power[tier] || 0);
  const rows = data.operators
    .map((op) => ({ ...op, shown: countFor(op) }))
    .filter((op) => op.shown > 0)
    .sort((a, b) => b.shown - a.shown);

  container.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle" id="operators-table-el">
        <thead><tr><th>#</th><th>Operatore</th><th>${POWER_TIER_LABELS[tier]}</th></tr></thead>
        <tbody>
          ${rows
            .map(
              (op, i) => `
                <tr class="${i < 3 ? 'table-warning' : ''}">
                  <td data-sort-value="${i + 1}">${i + 1}</td>
                  <td>
                    <span class="station-link" data-operator-popover="${op.name}">${op.name}</span>
                    ${op.active_unknown > 0 ? '<span class="badge bg-warning text-dark ms-1" title="Stato non aggiornato in tempo reale: occupazione stimata">stima</span>' : ''}
                  </td>
                  <td>${op.shown}</td>
                </tr>`
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
  enhanceTable(document.getElementById('operators-table-el'));
}

function wireOperatorsFilter() {
  const buttons = Array.from(document.querySelectorAll('#operators-power-filter button'));
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      if (statsPayloadForOperators) renderOperatorsTable(statsPayloadForOperators, btn.dataset.tier);
    });
  });
}

function renderOperatorsSection(stats, perOperatore) {
  const section = document.getElementById('operators-section');
  if (!stats || !stats.operators || stats.operators.length === 0) return;
  section.classList.remove('d-none');

  const operatorsTop3List = document.getElementById('operators-top3-list');
  operatorsTop3List.innerHTML = stats.operators
    .slice(0, 3)
    .map(
      (op, i) => `
      <div class="list-group-item d-flex justify-content-between align-items-center">
        <div><span class="badge bg-secondary me-2">#${i + 1}</span><strong class="station-link" data-operator-popover="${op.name}">${op.name}</strong></div>
        <span class="text-muted small">${op.count} colonnine</span>
      </div>`
    )
    .join('');
  if (window.EVUsage) EVUsage.wirePopovers(operatorsTop3List);

  statsPayloadForOperators = stats;
  renderOperatorsTable(stats);
  wireOperatorsFilter();

  const select = document.getElementById('operator-select');
  const drilldownList = document.getElementById('operator-drilldown-list');
  const operatorNames = Object.keys(perOperatore || {}).sort();

  if (operatorNames.length === 0) {
    select.innerHTML = '<option>Nessun operatore con storico sufficiente</option>';
    select.disabled = true;
    drilldownList.innerHTML = '';
    return;
  }

  select.disabled = false;
  select.innerHTML = operatorNames.map((name) => `<option value="${name}">${name}</option>`).join('');
  const renderDrilldown = () => {
    const items = (perOperatore[select.value] || {}).items || [];
    drilldownList.innerHTML = items.length
      ? items.map((item) => listItemHtml(item.rank, item.indirizzo, item.valore, item.lat, item.lon, item.id_evse)).join('')
      : '<div class="list-group-item text-muted small">Nessun dato.</div>';
    if (window.EVUsage) EVUsage.wirePopovers(drilldownList);
  };
  select.addEventListener('change', renderDrilldown);
  renderDrilldown();
}

// Tabella "Colonnine e punti di interesse" per categoria OSM, spostata qui
// da stats/app.js (dati da poi_proximity.json): sulla pagina Statistiche il
// nuovo blocco "POI / Luoghi" (poi_usage.json) la superava, mostrando
// l'uso reale per singolo POI invece di un aggregato per categoria.
function renderPoiProximity(data) {
  const section = document.getElementById('poi-proximity-section');
  const table = document.getElementById('poi-proximity-table');
  const note = document.getElementById('poi-proximity-note');
  if (!table || !section) return;
  const categorie = data && data.categorie ? Object.values(data.categorie) : [];
  if (categorie.length === 0) return;
  section.classList.remove('d-none');
  note.textContent = `Colonnine cittadine entro ${data.soglia_metri} m dal punto più vicino, per categoria. Fonte: ${data.fonte_poi}.`;
  const rows = categorie.slice().sort((a, b) => b.share - a.share);
  table.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle" id="poi-proximity-table-el">
        <thead><tr><th>Categoria</th><th>Colonnine entro soglia</th><th>% sul totale città</th><th>Esempio</th></tr></thead>
        <tbody>
          ${rows
            .map(
              (r) => `
                <tr>
                  <td>${r.label}</td>
                  <td data-sort-value="${r.count_entro_soglia}">${r.count_entro_soglia} / ${data.totale_colonnine_citta}</td>
                  <td data-sort-value="${r.share}">${r.share}%</td>
                  <td class="small text-muted">${
                    r.esempio
                      ? `${r.esempio.colonnina_indirizzo} → ${r.esempio.poi_nome} (${r.esempio.distanza_m} m)`
                      : '—'
                  }</td>
                </tr>`
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
  enhanceTable(document.getElementById('poi-proximity-table-el'));
}

async function loadCuriosities() {
  const [curiosResponse, statsResponse, usageResponse, poiProximityResponse] = await Promise.all([
    fetch('../data/curiosities.json'),
    fetch('../data/stats.json').catch(() => null),
    fetch('../../stations_usage.json').catch(() => null),
    fetch('../data/poi_proximity.json').catch(() => null),
  ]);
  if (usageResponse && usageResponse.ok && window.EVUsage) {
    EVUsage.setData(await usageResponse.json());
  }
  if (!curiosResponse.ok) {
    emptyState.classList.remove('d-none');
    return;
  }
  const payload = await curiosResponse.json();
  daysNote.textContent = `Calcolate su ${payload.days_collected} giorn${payload.days_collected === 1 ? 'o' : 'i'} di storico raccolto finora.`;

  const hasCuriosita = renderCuriosities(payload.curiosita);
  const top3 = payload.top3 || {};
  const hasUso = renderUsoBlock(top3.uso);
  const hasPotenza = renderTop3Block('potenza', top3.potenza);
  wireUsoFilter();

  if (statsResponse && statsResponse.ok) {
    renderOperatorsSection(await statsResponse.json(), payload.per_operatore);
  }

  if (poiProximityResponse && poiProximityResponse.ok) {
    renderPoiProximity(await poiProximityResponse.json());
  }

  if (!hasCuriosita && !hasUso && !hasPotenza) {
    emptyState.classList.remove('d-none');
  }
}

loadCuriosities();
