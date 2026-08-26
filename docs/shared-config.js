// shared-config.js — Legge docs/config.json (stessa fonte usata da config.py
// lato Python) e applica il nome del comune al DOM: elementi [data-comune],
// più il tag <title> (i meta tag og/twitter restano statici, generati a mano
// per pagina — non letti da crawler che eseguono JS).
//
// Il percorso di config.json varia con la profondità della pagina (index.html
// è alla radice di docs/, le pagine sotto stats/ sono uno o due livelli
// sotto): va passato via data-config sul tag <script> che include questo
// file, es. <script src="../shared-config.js" data-config="../config.json">.
(function () {
  const script = document.currentScript;
  const configPath = (script && script.dataset.config) || 'config.json';

  window.EVConfig = {
    ready: fetch(configPath)
      .then((r) => r.json())
      .then((cfg) => {
        const nome = cfg.area_nome || cfg.comune;
        document.querySelectorAll('[data-comune]').forEach((el) => {
          el.textContent = nome;
        });
        document.title = document.title.replace(/Trento/g, nome);
        return cfg;
      })
      .catch((err) => {
        console.warn('config.json non disponibile, resto sui valori di default:', err);
        return { comune: 'Trento', provincia: 'TN' };
      }),
  };
})();
