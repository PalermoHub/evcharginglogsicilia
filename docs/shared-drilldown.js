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
  function barOption(segments, axisMax, pctBase) {
    const canLabel = (v) => axisMax > 0 && v / axisMax >= 0.12;
    return {
      tooltip: {
        trigger: 'item',
        formatter: (p) => {
          const seg = segments[p.seriesIndex];
          let html = `${p.seriesName}: <strong>${p.value}</strong> (${pct1(p.value, pctBase)}%)`;
          if (seg && seg.extraLine) html += `<br>${seg.extraLine}`;
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
        itemStyle: {
          color: seg.color,
          borderColor: SURFACE_COLOR,
          borderWidth: 2,
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

  // counts = { attivaReale, attivaStimata, inUso, nonAttiva, monitorabili }.
  // Ritorna le due istanze ECharts (o null se ECharts non è caricato),
  // utile solo per test manuali dalla console.
  function render(container, counts) {
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

    const a22 = counts.a22 || 0;
    const a22Label = counts.a22Label || 'autostrada';
    container.innerHTML = `
      <div class="fw-semibold mb-1"><strong>${totale}</strong> colonnine in totale</div>
      ${a22 ? `<div class="text-muted small mb-1">di cui <strong>${a22}</strong> in autostrada (${a22Label})</div>` : ''}
      <p class="text-muted small mb-3">Le colonnine stimate sono quelle attive ma di cui non si ha informazione se sono in uso.</p>
      <div class="drilldown-bar-top"></div>
      <div class="drilldown-connector"><svg role="presentation"></svg></div>
      <div class="drilldown-bar-bottom-wrap"><div class="drilldown-bar-bottom"></div></div>
      <div class="map-legend mt-3">
        <span class="map-legend-item"><span class="map-legend-dot" style="background:${ACCENT}"></span>In uso · <strong>${inUso}</strong></span>
        <span class="map-legend-item"><span class="map-legend-dot" style="background:${HERO_GREEN}"></span>Attiva (reale) · <strong>${attivaReale}</strong></span>
        <span class="map-legend-item"><span class="map-legend-dot" style="background:${HERO_GREEN_LIGHT}"></span>Attiva (stimata) · <strong>${attivaStimata}</strong></span>
        <span class="map-legend-item"><span class="map-legend-dot" style="background:${STATUS_RED}"></span>Non attiva · <strong>${nonAttiva}</strong></span>
      </div>
      <p class="text-muted small mt-3 mb-0">Non tutte le colonnine sono monitorabili: la categoria "in uso" può essere mostrata solo per quelle disponibili su cui l'app riesce a rilevare l'occupazione in tempo reale.</p>
    `;

    if (typeof echarts === 'undefined') return null;

    const topEl = container.querySelector('.drilldown-bar-top');
    const bottomWrapEl = container.querySelector('.drilldown-bar-bottom-wrap');
    const bottomEl = container.querySelector('.drilldown-bar-bottom');
    const svgEl = container.querySelector('.drilldown-connector svg');

    // La barra "Di cui" è larga esattamente quanto il segmento Attive
    // della barra sopra: è letteralmente lo stesso sottoinsieme, solo
    // scomposto — da qui il connettore a staffa che li unisce.
    bottomWrapEl.style.width = `${fracAttiva * 100}%`;

    const topChart = echarts.init(topEl, 'evtrento-dark');
    topChart.setOption(barOption([{ name: 'Attive', value: attiva, color: HERO_GREEN }, { name: 'Non attive', value: nonAttiva, color: STATUS_RED }], totale, totale));

    const bottomChart = echarts.init(bottomEl, 'evtrento-dark');
    bottomChart.setOption(
      barOption(
        [
          {
            name: 'In uso',
            value: inUso,
            color: ACCENT,
            extraLine: `Quota su monitorabili: <strong>${formatPct(quotaInUso)}%</strong>`,
          },
          { name: 'Attiva (reale)', value: attivaReale, color: HERO_GREEN },
          { name: 'Attiva (stimata)', value: attivaStimata, color: HERO_GREEN_LIGHT, textColor: '#173318' },
        ],
        // Scala visiva della barra: il totale delle attive (larga quanto
        // il segmento Attive sopra). Percentuali del tooltip invece sul
        // totale generale (`totale`, non `attiva`) per tutti i segmenti.
        attiva,
        totale
      )
    );

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
