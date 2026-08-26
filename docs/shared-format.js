// shared-format.js — formattazione delle date in italiano, uniforme su
// tutto il sito: giorno della settimana abbreviato, giorno del mese a due
// cifre, mese abbreviato, anno a 4 cifre, ora HH:mm quando presente.
// Es. dateTime("2026-08-05T22:22:00") -> "mer 05 ago 2026, 22:22"
//     dateOnly("2026-08-05")          -> "mer 05 ago 2026"
//     monthYear("2026-08")            -> "ago 2026"
//
// Assegnato esplicitamente a window: un `const` a livello di script
// classico non diventa una proprietà di `window` (vedi shared-usage.js).
window.EVFormat = (() => {
  const DATE_OPTS = { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' };
  const TIME_OPTS = { hour: '2-digit', minute: '2-digit', hour12: false };

  function dateTime(isoLike) {
    const d = new Date(isoLike);
    if (Number.isNaN(d.getTime())) return '';
    return `${d.toLocaleDateString('it-IT', DATE_OPTS)}, ${d.toLocaleTimeString('it-IT', TIME_OPTS)}`;
  }

  // Data senza ora (es. "2026-08-05"): si forza la mezzanotte locale
  // esplicita, altrimenti "YYYY-MM-DD" verrebbe interpretato come UTC e
  // potrebbe scivolare al giorno precedente nei fusi orari negativi.
  function dateOnly(isoDate) {
    const d = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('it-IT', DATE_OPTS);
  }

  // "YYYY-MM" -> "ago 2026": per un aggregato mensile non ha senso un
  // giorno/settimana, quindi si omettono.
  function monthYear(yyyyMm) {
    const [y, m] = String(yyyyMm).split('-').map(Number);
    const d = new Date(y, (m || 1) - 1, 1);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('it-IT', { month: 'short', year: 'numeric' });
  }

  const pad2 = (n) => String(n).padStart(2, '0');

  // Formato richiesto specificamente per il contenuto dei popup/popover
  // (mappa e hover su nome colonnina/operatore): DD/MM/YYYY [HH:MM],
  // diverso dal formato "mer 05 ago 2026" usato nel resto del sito perché
  // più compatto in uno spazio piccolo come un popup.
  function popupDateTime(isoLike) {
    const d = new Date(isoLike);
    if (Number.isNaN(d.getTime())) return '';
    return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }

  function popupDate(isoDate) {
    const d = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(d.getTime())) return '';
    return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
  }

  // DD/MM/YY: per le etichette sugli assi dei grafici, dove lo spazio
  // orizzontale per categoria è poco e un anno a 4 cifre costringerebbe a
  // ruotare il testo.
  function dateShort(isoDate) {
    const d = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(d.getTime())) return '';
    return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${String(d.getFullYear()).slice(-2)}`;
  }

  return { dateTime, dateOnly, monthYear, popupDateTime, popupDate, dateShort };
})();
