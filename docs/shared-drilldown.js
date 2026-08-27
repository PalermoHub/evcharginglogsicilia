// shared-drilldown.js — componente "colonnine totali -> di cui" condiviso
// da home (docs/app.js) e pagina Statistiche (docs/stats/app.js): una barra
// impilata Attive/Non attive, un connettore a staffa+freccia verso una
// seconda barra "Di cui" che scompone le sole colonnine attive in
// disponibili non monitorabili (stimate) / disponibili monitorabili
// (reale) / in uso.
//
// Colori duplicati qui volutamente: stessa convenzione già in uso in
// docs/app.js e docs/stats/app.js, dove ogni script che disegna grafici
// tiene la propria copia della palette (ECharts non legge le CSS custom
// properties, quindi condividerle da un'unica fonte non semplificherebbe
// nulla lato chiamante).
window.EVDrilldown = (() => {
  const HERO_GREEN = '#1da542';
  const HERO_GREEN_LIGHT = '#8bc34a';
  const ACCENT = '#28a1bd';
  const STATUS_RED = '#b02a2a';
  const SURFACE_COLOR = '#171f30';

  let uid = 0;

  // Percentuale con 2 decimali in stile italiano — stessa precisione
  // ovunque nel sito si scriva "X in uso su Y monitorabili" (didascalia
  // gauge home, gauge Statistiche, tooltip di questo componente): un
  // valore identico ripetuto in punti diversi dell'app perde credibilità
  // se arrotondato diversamente da un posto all'altro.
  function ratio(numerator, denominator) {
    return denominator ? (numerator / denominator) * 100 : 0;
  }

  function formatPct(value) {
    return value.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function pct1(value, total) {
    return total ? Math.round((value / total) * 1000) / 10 : 0;
  }

  // Una singola barra orizzontale a categoria unica (stesso schema delle
  // altre stacked bar del sito). `axisMax` è la scala visiva della barra
  // (controlla anche la soglia >=12% sotto cui l'etichetta interna del
  // segmento resta nascosta, raggiungibile comunque da legenda e
  // tooltip); `pctBase` è il denominatore usato SOLO per la percentuale
  // nel tooltip — le due cose sono deliberatamente slegate: la barra "Di
  // cui" è scalata sul totale delle attive (la sua stessa larghezza), ma
  // le percentuali che mostra restano sul totale generale delle
  // colonnine, come richiesto.
  function barOption(segments, axisMax, pctBase, interactive) {
    const canLabel = (v) => axisMax > 0 && v / axisMax >= 0.12;
    const anySelected = interactive && segments.some((seg) => seg.selected);
    return {
      tooltip: {
        trigger: 'item',
        formatter: (p) => {
          const seg = segments[p.seriesIndex];
          let html = `${p.seriesName}: <strong>${p.value}</strong> (${pct1(p.value, pctBase)}%)`;
          if (seg && seg.extraLine) html += `<br>${seg.extraLine}`;
          if (interactive && seg && seg.filterValue) html += '<br><em>Clicca per filtrare per stato</em>';
          return html;
        },
      },
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'value', show: false, max: axisMax || 1 },
      yAxis: { type: 'category', data: [''], show: false },
      series: segments.map((seg, i) => ({
        name: seg.name,
        type: 'bar',
        stack: 'totale',
        barWidth: '100%',
        cursor: interactive && seg.filterValue ? 'pointer' : 'default',
        itemStyle: {
          color: seg.color,
          opacity: anySelected && !seg.selected ? 0.4 : 1,
          borderColor: seg.selected ? '#ffffff' : SURFACE_COLOR,
          borderWidth: seg.selected ? 3 : 2,
          borderRadius: i === 0 ? [6, 0, 0, 6] : i === segments.length - 1 ? [0, 6, 6, 0] : 0,
        },
        label: { show: canLabel(seg.value), position: 'inside', color: seg.textColor || '#fff', formatter: () => seg.value },
        data: [seg.value],
      })),
    };
  }

  // Staffa (linea con due "orecchie" verticali che salgono a toccare la
  // barra sopra) più una freccia verticale verso la barra sotto: il
  // collegamento visivo esplicito tra "queste colonnine attive" e il loro
  // dettaglio. Ricalcolata in pixel reali a ogni resize invece di usare un
  // viewBox percentuale con preserveAspectRatio="none": uno scaling non
  // uniforme deformerebbe la punta della freccia.
  function drawConnector(svg, fracEnd) {
    const width = svg.parentElement.clientWidth;
    const height = 56;
    if (!width) return;
    const xEnd = Math.max(1, width * fracEnd);
    const xMid = xEnd / 2;
    const markerId = `dd-arrow-${uid++}`;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = `
      <defs>
        <marker id="${markerId}" viewBox="0 0 10 10" refX="5" refY="6" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
        </marker>
      </defs>
      <g stroke="currentColor" stroke-width="1.5" opacity="0.55" fill="none">
        <line x1="0.75" y1="0" x2="0.75" y2="14"></line>
        <line x1="${xEnd - 0.75}" y1="0" x2="${xEnd - 0.75}" y2="14"></line>
        <line x1="0" y1="14" x2="${xEnd}" y2="14"></line>
      </g>
      <line x1="${xMid}" y1="14" x2="${xMid}" y2="${height - 8}" stroke="currentColor" stroke-width="1.5" opacity="0.55" marker-end="url(#${markerId})"></line>
      <text x="${Math.min(xMid + 14, width - 4)}" y="${height / 2 + 8}" font-size="12" font-style="italic" fill="currentColor" opacity="0.8">Di cui</text>
    `;
  }

  // Le 4 etichette di stato così come le restituisce displayState() in
  // docs/app.js (stessa stringa usata come valore della sfaccettatura
  // "Stato" — vedi FACETS): il grafico e la legenda diventano filtri
  // interconnessi con quel pannello solo se usano identiche stringhe,
  // non le etichette di comodo dei segmenti del grafico (es. "Non attive"
  // plurale vs "Non attiva" singolare del filtro).
  const STATO_IN_USO = 'In uso';
  const STATO_ATTIVA_REALE = 'Attiva (reale)';
  const STATO_ATTIVA_STIMATA = 'Attiva (stimata)';
  const STATO_NON_ATTIVA = 'Non attiva';
  const STATO_ATTIVE_GROUP = [STATO_IN_USO, STATO_ATTIVA_REALE, STATO_ATTIVA_STIMATA];

  // counts = { attivaReale, attivaStimata, inUso, nonAttiva, monitorabili }.
  // `onToggle(value)`, se passato, rende il grafico e la legenda dei filtri
  // cliccabili, interconnessi con lo stesso stato condiviso da tutte le
  // altre sfaccettature (docs/app.js, activeFilters.stato): `value` è una
  // singola etichetta di stato, o un array di etichette per il segmento
  // aggregato "Attive" della barra in alto. `selected` è il Set (o array)
  // di etichette attualmente selezionate altrove (es. dal pannello Stato),
  // usato per evidenziare qui lo stesso stato — l'interconnessione va in
  // entrambe le direzioni. Ritorna le due istanze ECharts (o null se
  // ECharts non è caricato), utile solo per test manuali dalla console.
  function render(container, counts, { onToggle, selected } = {}) {
    const selectedSet = selected instanceof Set ? selected : new Set(selected || []);
    const interactive = typeof onToggle === 'function';
    const isSelected = (label) => selectedSet.has(label);
    const groupSelected = STATO_ATTIVE_GROUP.every(isSelected);

    const attivaReale = counts.attivaReale || 0;
    const attivaStimata = counts.attivaStimata || 0;
    const inUso = counts.inUso || 0;
    const nonAttiva = counts.nonAttiva || 0;
    const attiva = attivaReale + attivaStimata + inUso;
    const totale = attiva + nonAttiva;
    const fracAttiva = totale ? attiva / totale : 0;
    // "Monitorabili" = colonnine che ADESSO dicono se sono libere o occupate
    // (attivaReale + inUso, vedi summarize in docs/app.js): esclude le
    // "Non Attivo" che, pur appartenendo a un operatore usage_observable,
    // in questo momento sono spente/guaste — stessa quota mostrata nel
    // gauge accanto.
    const monitorabili = counts.monitorabili || 0;
    const quotaInUso = ratio(inUso, monitorabili);

    // Ogni voce di legenda porta il proprio valore di sfaccettatura in
    // data-filter-value: cliccarla equivale a spuntare quella stessa
    // opzione nel pannello "Stato" (stesso Set condiviso, vedi
    // toggleStatoFilter in docs/app.js) — da qui "is-selected"/"is-dimmed"
    // per riflettere qui lo stato attivo, in entrambe le direzioni.
    const legendItem = (label, color, value, textColor) => {
      const sel = isSelected(label);
      const cls = ['map-legend-item'];
      if (interactive) cls.push('filter-legend-item');
      if (sel) cls.push('is-selected');
      else if (selectedSet.size) cls.push('is-dimmed');
      const attrs = interactive
        ? `role="button" tabindex="0" data-filter-value="${label}" aria-pressed="${sel}"`
        : '';
      return `<span class="${cls.join(' ')}" ${attrs}><span class="map-legend-dot" style="background:${color}"></span>${label} · <strong${textColor ? ` style="color:${textColor}"` : ''}>${value}</strong></span>`;
    };

    const autostrada = counts.autostrada || 0;
    const autostradaLabel = counts.autostradaLabel || 'autostrada';
    container.innerHTML = `
      <div class="fw-semibold mb-1"><strong>${totale}</strong> colonnine in totale</div>
      ${autostrada ? `<div class="text-muted small mb-1">di cui <strong>${autostrada}</strong> in autostrada (${autostradaLabel})</div>` : ''}
      <p class="text-muted small mb-3">Le colonnine stimate sono quelle attive ma di cui non si ha informazione se sono in uso.</p>
      <div class="drilldown-bar-top"></div>
      <div class="drilldown-connector"><svg role="presentation"></svg></div>
      <div class="drilldown-bar-bottom-wrap"><div class="drilldown-bar-bottom"></div></div>
      <div class="map-legend mt-3">
        ${legendItem(STATO_IN_USO, ACCENT, inUso)}
        ${legendItem(STATO_ATTIVA_REALE, HERO_GREEN, attivaReale)}
        ${legendItem(STATO_ATTIVA_STIMATA, HERO_GREEN_LIGHT, attivaStimata)}
        ${legendItem(STATO_NON_ATTIVA, STATUS_RED, nonAttiva)}
      </div>
      <p class="text-muted small mt-3 mb-0">Non tutte le colonnine sono monitorabili: la categoria "in uso" può essere mostrata solo per quelle disponibili su cui l'app riesce a rilevare l'occupazione in tempo reale.</p>
      ${interactive ? '<p class="text-muted small mt-2 mb-0">Clicca una barra o la legenda per filtrare per stato — si somma agli altri filtri attivi.</p>' : ''}
    `;

    if (interactive) {
      container.querySelectorAll('[data-filter-value]').forEach((el) => {
        const trigger = () => onToggle(el.dataset.filterValue);
        el.addEventListener('click', trigger);
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            trigger();
          }
        });
      });
    }

    if (typeof echarts === 'undefined') return null;

    const topEl = container.querySelector('.drilldown-bar-top');
    const bottomWrapEl = container.querySelector('.drilldown-bar-bottom-wrap');
    const bottomEl = container.querySelector('.drilldown-bar-bottom');
    const svgEl = container.querySelector('.drilldown-connector svg');

    // La barra "Di cui" è larga esattamente quanto il segmento Attive
    // della barra sopra: è letteralmente lo stesso sottoinsieme, solo
    // scomposto — da qui il connettore a staffa che li unisce.
    bottomWrapEl.style.width = `${fracAttiva * 100}%`;

    const topSegments = [
      { name: 'Attive', value: attiva, color: HERO_GREEN, filterValue: STATO_ATTIVE_GROUP, selected: groupSelected },
      { name: 'Non attive', value: nonAttiva, color: STATUS_RED, filterValue: STATO_NON_ATTIVA, selected: isSelected(STATO_NON_ATTIVA) },
    ];
    const topChart = echarts.init(topEl, 'evtrento-dark');
    topChart.setOption(barOption(topSegments, totale, totale, interactive));

    const bottomSegments = [
      {
        name: STATO_IN_USO,
        value: inUso,
        color: ACCENT,
        extraLine: `Quota su monitorabili: <strong>${formatPct(quotaInUso)}%</strong>`,
        filterValue: STATO_IN_USO,
        selected: isSelected(STATO_IN_USO),
      },
      { name: STATO_ATTIVA_REALE, value: attivaReale, color: HERO_GREEN, filterValue: STATO_ATTIVA_REALE, selected: isSelected(STATO_ATTIVA_REALE) },
      { name: STATO_ATTIVA_STIMATA, value: attivaStimata, color: HERO_GREEN_LIGHT, textColor: '#173318', filterValue: STATO_ATTIVA_STIMATA, selected: isSelected(STATO_ATTIVA_STIMATA) },
    ];
    const bottomChart = echarts.init(bottomEl, 'evtrento-dark');
    bottomChart.setOption(
      barOption(
        bottomSegments,
        // Scala visiva della barra: il totale delle attive (larga quanto
        // il segmento Attive sopra). Percentuali del tooltip invece sul
        // totale generale (`totale`, non `attiva`) per tutti i segmenti.
        attiva,
        totale,
        interactive
      )
    );

    if (interactive) {
      [
        [topChart, topSegments],
        [bottomChart, bottomSegments],
      ].forEach(([chart, segs]) => {
        chart.on('click', (p) => {
          const seg = segs[p.seriesIndex];
          if (seg && seg.filterValue) onToggle(seg.filterValue);
        });
      });
    }

    drawConnector(svgEl, fracAttiva);

    function handleResize() {
      topChart.resize();
      bottomChart.resize();
      drawConnector(svgEl, fracAttiva);
    }
    window.addEventListener('resize', handleResize);
    // Il layout può cambiare larghezza anche senza un resize della
    // finestra (es. una colonna Bootstrap che si stacca a un breakpoint
    // per via del contenuto dei fratelli): ResizeObserver copre anche
    // questo caso, window.resize resta come fallback per i browser senza.
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(() => handleResize()).observe(container);
    }

    return { topChart, bottomChart };
  }

  return { render, ratio, formatPct };
})();
