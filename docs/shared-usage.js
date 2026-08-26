// shared-usage.js — contenuto HTML condiviso per le statistiche di una
// colonnina o di un operatore, usato sia dal popup della mappa (al click)
// sia dai popover al passaggio del mouse sul nome di una colonnina/
// operatore in qualsiasi altra pagina (tabelle, liste, classifiche).
//
// Una sola fonte per questo HTML evita di duplicare la stessa logica in
// app.js, stats/app.js e funfacts/app.js.

// Assegnato esplicitamente a window: un `const`/`let` a livello di script
// classico NON diventa una proprietà di `window` (a differenza di `var` e
// delle function declaration), quindi ogni `if (window.EVUsage)` altrove
// fallirebbe silenziosamente pur essendo `EVUsage` accessibile come
// identificatore bare nello stesso scope globale.
window.EVUsage = (() => {
  let data = null;

  function setData(json) {
    data = json;
  }

  function oraPiuUsata(profiloOrario) {
    if (!profiloOrario) return null;
    const best = profiloOrario.reduce(
      (acc, cur) => (cur.quota_charging > (acc ? acc.quota_charging : -1) ? cur : acc),
      null
    );
    return best && best.quota_charging > 0 ? best : null;
  }

  function veicoliRiga(veicoli) {
    if (!veicoli) return '';
    return `<dt>Veicoli serviti</dt><dd>ultima ora ${veicoli.ultima_ora} · 24h ${veicoli.ultime_24h} · 7gg ${veicoli.ultimi_7_giorni} · 30gg ${veicoli.ultimi_30_giorni}</dd>`;
  }

  function stationHtml(idEvse, { usageObservable = true } = {}) {
    if (!usageObservable) {
      return '<div class="popup-usage small text-muted mt-2">Per questa colonnina l\'operatore non distingue occupata da libera: l\'uso non è calcolabile.</div>';
    }
    const usage = data && data.stazioni ? data.stazioni[idEvse] : null;
    if (!usage) {
      return '<div class="popup-usage small text-muted mt-2">Dati d\'uso non ancora disponibili.</div>';
    }
    if (usage.n_sessioni === 0) {
      return '<div class="popup-usage small text-muted mt-2">Nessuna sessione di ricarica osservata finora.</div>';
    }

    const ora = oraPiuUsata(usage.profilo_orario);
    const righe = [
      `<dt>Sessioni osservate</dt><dd>${usage.n_sessioni}</dd>`,
      usage.durata_media_minuti != null ? `<dt>Durata media</dt><dd>${usage.durata_media_minuti} min</dd>` : '',
      usage.energia_totale_kwh_stimata != null
        ? `<dt>Energia erogata (stima)</dt><dd>${usage.energia_totale_kwh_stimata} kWh</dd>`
        : '',
      usage.energia_oggi_kwh != null
        ? `<dt>Energia oggi (dalle 00:00, ora italiana)</dt><dd>${usage.energia_oggi_kwh} kWh</dd>`
        : '',
      veicoliRiga(usage.veicoli_serviti),
      ora ? `<dt>Ora più usata</dt><dd>${ora.ora}:00 (${ora.quota_charging}% delle rilevazioni)</dd>` : '',
      usage.giorno_settimana_piu_usato
        ? `<dt>Giorno più usato</dt><dd>${usage.giorno_settimana_piu_usato.giorno}</dd>`
        : '<dt>Giorno più usato</dt><dd class="text-muted">servono più giorni di storico</dd>',
      usage.giorno_record
        ? `<dt>Giorno record</dt><dd>${window.EVFormat ? EVFormat.popupDate(usage.giorno_record.data) : usage.giorno_record.data} (${usage.giorno_record.minuti_ricarica_totali} min totali)</dd>`
        : '',
    ]
      .filter(Boolean)
      .join('');

    return `<dl class="popup-usage small mt-2 mb-0">${righe}</dl>`;
  }

  function operatorHtml(cpo) {
    const list = data && data.city && data.city.operatori_per_uso ? data.city.operatori_per_uso : [];
    const rec = list.find((o) => o.cpo === cpo);
    if (!rec) {
      return '<div class="popup-usage small text-muted mb-0">Dati d\'uso non disponibili per questo operatore.</div>';
    }
    return `<dl class="popup-usage small mb-0">
      <dt>Colonnine</dt><dd>${rec.n_colonnine}</dd>
      <dt>Sessioni osservate</dt><dd>${rec.n_sessioni}</dd>
      <dt>Energia erogata (stima)</dt><dd>${rec.energia_totale_kwh_stimata} kWh</dd>
    </dl>`;
  }

  // Aggancia un popover Bootstrap (mostrato al passaggio del mouse) a ogni
  // elemento [data-station-popover]/[data-operator-popover] trovato dentro
  // `root`. Va richiamata dopo ogni render di tabelle/liste dinamiche (gli
  // elementi che non esistevano ancora non possono essere agganciati
  // prima). Idempotente: un elemento già agganciato viene saltato.
  function wirePopovers(root = document) {
    if (typeof bootstrap === 'undefined') return;
    root.querySelectorAll('[data-station-popover], [data-operator-popover]').forEach((el) => {
      if (el._evPopover) return;
      const idEvse = el.getAttribute('data-station-popover');
      const cpo = el.getAttribute('data-operator-popover');
      const content = cpo
        ? () => operatorHtml(cpo)
        : () => stationHtml(idEvse, { usageObservable: el.getAttribute('data-usage-observable') !== 'false' });
      el._evPopover = new bootstrap.Popover(el, {
        trigger: 'hover focus',
        html: true,
        placement: 'auto',
        content,
        sanitize: false,
      });
    });
  }

  return { setData, stationHtml, operatorHtml, wirePopovers };
})();
