// shared-chart-tools.js — fullscreen + esportazione immagine per un
// grafico ECharts, riusato da ogni grafico della pagina Statistiche (e
// utilizzabile ovunque nel sito). Un'unica funzione invece di ripetere la
// stessa configurazione di toolbox in ogni renderXxx(): vedi il piano di
// questa iterazione per l'elenco dei grafici che la usano.
//
// Uso: dopo chart.setOption(...), richiamare
//   EVChartTools.attach(chart, containerEl)
// Idempotente sullo stesso containerEl (il listener di resize non viene
// agganciato due volte).
window.EVChartTools = (() => {
  // Icone Material Design (viewBox 24x24), compatibili col formato
  // "path://" di ECharts che ne calcola da solo il bounding box.
  const ICON_FULLSCREEN = 'path://M3,3H9V5H5V9H3V3M21,3V9H19V5H15V3H21M3,21V15H5V19H9V21H3M21,21H15V19H19V15H21V21Z';
  const ICON_FULLSCREEN_EXIT = 'path://M5,5H9V7H7V9H5V5M15,5H19V9H17V7H15V5M17,15H19V19H15V17H17V15M9,17V19H5V15H7V17H9Z';

  function toggleFullscreen(containerEl) {
    if (document.fullscreenElement === containerEl) {
      document.exitFullscreen();
    } else if (containerEl.requestFullscreen) {
      containerEl.requestFullscreen();
    }
  }

  // Attacca toolbox (fullscreen + salva immagine) e ridimensiona il
  // grafico quando si entra/esce dal fullscreen — senza questo la canvas
  // resta alla dimensione calcolata prima del cambio di layout.
  function attach(chart, containerEl, { filename = 'grafico-evtrento' } = {}) {
    if (!chart || !containerEl) return;
    containerEl.classList.add('ev-chart-fullscreen-target');

    chart.setOption({
      toolbox: {
        right: 8,
        top: 4,
        iconStyle: { borderColor: '#aeb9cc' },
        emphasis: { iconStyle: { borderColor: '#ffffff' } },
        feature: {
          myFullscreen: {
            show: true,
            title: 'Schermo intero',
            icon: ICON_FULLSCREEN,
            onclick: () => toggleFullscreen(containerEl),
          },
          saveAsImage: {
            show: true,
            title: 'Salva immagine',
            name: filename,
            backgroundColor: '#0b1120',
            pixelRatio: 2,
          },
        },
      },
    });

    if (containerEl._evChartToolsWired) return;
    containerEl._evChartToolsWired = true;
    document.addEventListener('fullscreenchange', () => {
      const isFs = document.fullscreenElement === containerEl;
      if (!isFs && document.fullscreenElement !== null) return; // fullscreen su un altro grafico
      chart.setOption({
        toolbox: { feature: { myFullscreen: { icon: isFs ? ICON_FULLSCREEN_EXIT : ICON_FULLSCREEN } } },
      });
      // Il resize va ritardato di un istante: al momento dell'evento il
      // browser non ha ancora applicato le nuove dimensioni CSS al
      // contenitore (:fullscreen), quindi chart.resize() letto subito
      // userebbe ancora le misure vecchie.
      requestAnimationFrame(() => chart.resize());
    });
  }

  return { attach };
})();
