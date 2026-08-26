// shared-table.js — ricerca full-text, ordinamento per colonna, paginazione
// (10 righe per pagina di default) per una <table> già popolata. Nessuna
// libreria esterna: legge le righe esistenti nel <tbody>, non richiede un
// formato dati particolare.
//
// Uso: enhanceTable(document.getElementById('la-mia-tabella'))
// Richiamabile più volte sulla stessa tabella (es. dopo un re-render dei
// dati): rimuove toolbar/paginazione precedenti e ripristina lo stato.

function enhanceTable(tableEl, { pageSize = 25 } = {}) {
  if (!tableEl) return;
  const tbody = tableEl.querySelector('tbody');
  const thead = tableEl.querySelector('thead');
  if (!tbody || !thead) return;

  const allRows = Array.from(tbody.querySelectorAll('tr'));
  let sortCol = null;
  let sortDir = 1;
  let searchTerm = '';
  let page = 1;

  const wrapId = tableEl.id ? `${tableEl.id}-search` : null;
  const pagId = tableEl.id ? `${tableEl.id}-pagination` : null;
  if (wrapId) document.getElementById(wrapId)?.remove();
  if (pagId) document.getElementById(pagId)?.remove();

  const toolbar = document.createElement('div');
  toolbar.className = 'mb-2 d-flex flex-wrap align-items-center justify-content-between gap-2';
  if (wrapId) toolbar.id = wrapId;
  toolbar.innerHTML = `
    <input type="search" class="form-control form-control-sm ev-table-search" style="max-width: 260px" placeholder="Cerca...">
    <div class="d-flex align-items-center gap-2">
      <label class="small text-muted mb-0">Righe per pagina</label>
      <select class="form-select form-select-sm ev-table-page-size" style="width: auto">
        <option value="10">10</option>
        <option value="25">25</option>
        <option value="50">50</option>
        <option value="100">100</option>
      </select>
      <button type="button" class="btn btn-sm btn-outline-secondary ev-table-fullscreen-btn">Schermo intero</button>
    </div>
  `;
  tableEl.parentElement.insertBefore(toolbar, tableEl);
  const searchInput = toolbar.querySelector('.ev-table-search');
  const pageSizeSelect = toolbar.querySelector('.ev-table-page-size');
  const fullscreenBtn = toolbar.querySelector('.ev-table-fullscreen-btn');
  pageSizeSelect.value = String(pageSize);

  // Il target del fullscreen è la card che contiene la tabella (titolo,
  // filtri ecc. inclusi), non solo il <table> — altrimenti in schermo
  // intero si vedrebbe la tabella senza contesto.
  const fsTarget = tableEl.closest('.card') || tableEl.parentElement;
  fsTarget.classList.add('ev-table-fullscreen-target');
  fullscreenBtn.addEventListener('click', () => {
    if (document.fullscreenElement === fsTarget) document.exitFullscreen();
    else if (fsTarget.requestFullscreen) fsTarget.requestFullscreen();
  });
  if (!fsTarget._evTableFsWired) {
    fsTarget._evTableFsWired = true;
    document.addEventListener('fullscreenchange', () => {
      const isFs = document.fullscreenElement === fsTarget;
      const btn = fsTarget.querySelector('.ev-table-fullscreen-btn');
      if (btn) btn.textContent = isFs ? 'Esci da schermo intero' : 'Schermo intero';
    });
  }

  pageSizeSelect.addEventListener('change', () => {
    pageSize = parseInt(pageSizeSelect.value, 10) || 10;
    page = 1;
    render();
  });

  const paginationWrap = document.createElement('div');
  if (pagId) paginationWrap.id = pagId;
  paginationWrap.className = 'mt-2';
  tableEl.parentElement.insertBefore(paginationWrap, tableEl.nextSibling);

  const ths = Array.from(thead.querySelectorAll('th'));
  ths.forEach((th, i) => {
    th.style.cursor = 'pointer';
    th.style.userSelect = 'none';
    th.addEventListener('click', () => {
      if (sortCol === i) sortDir *= -1;
      else {
        sortCol = i;
        sortDir = 1;
      }
      ths.forEach((t) => t.querySelectorAll('.sort-indicator').forEach((el) => el.remove()));
      const ind = document.createElement('span');
      ind.className = 'sort-indicator small ms-1';
      ind.textContent = sortDir === 1 ? '▲' : '▼';
      th.appendChild(ind);
      page = 1;
      render();
    });
  });

  searchInput.addEventListener('input', () => {
    searchTerm = searchInput.value.trim().toLowerCase();
    page = 1;
    render();
  });

  function cellText(tr, i) {
    const cell = tr.children[i];
    if (!cell) return '';
    return (cell.dataset.sortValue ?? cell.textContent).toString().trim();
  }

  // Pagine da mostrare come numeri cliccabili: sempre prima, ultima e le
  // vicine alla corrente, con "…" per il resto — invece di un bottone per
  // ognuna delle N pagine, che con centinaia di risultati diventa un muro
  // di numeri costretto a scorrere in orizzontale.
  function pageWindow(totalPages) {
    const span = 2;
    const nums = new Set([1, totalPages]);
    for (let p = page - span; p <= page + span; p += 1) {
      if (p >= 1 && p <= totalPages) nums.add(p);
    }
    const sorted = Array.from(nums).sort((a, b) => a - b);
    const out = [];
    sorted.forEach((p, i) => {
      if (i > 0 && p - sorted[i - 1] > 1) out.push('…');
      out.push(p);
    });
    return out;
  }

  function renderPagination(totalPages, totalRows) {
    if (totalPages <= 1) {
      paginationWrap.innerHTML = `<div class="small text-muted">${totalRows} risultat${totalRows === 1 ? 'o' : 'i'}</div>`;
      return;
    }
    const items = [
      `<li class="page-item ${page === 1 ? 'disabled' : ''}"><button type="button" class="page-link" data-page="${page - 1}" ${page === 1 ? 'disabled' : ''}>‹</button></li>`,
    ];
    pageWindow(totalPages).forEach((p) => {
      items.push(
        p === '…'
          ? '<li class="page-item disabled"><span class="page-link">…</span></li>'
          : `<li class="page-item ${p === page ? 'active' : ''}"><button type="button" class="page-link" data-page="${p}">${p}</button></li>`
      );
    });
    items.push(
      `<li class="page-item ${page === totalPages ? 'disabled' : ''}"><button type="button" class="page-link" data-page="${page + 1}" ${page === totalPages ? 'disabled' : ''}>›</button></li>`
    );
    paginationWrap.innerHTML = `
      <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div class="small text-muted">${totalRows} risultati · pagina ${page} di ${totalPages}</div>
        <ul class="pagination pagination-sm mb-0">${items.join('')}</ul>
      </div>`;
    paginationWrap.querySelectorAll('[data-page]:not([disabled])').forEach((btn) => {
      btn.addEventListener('click', () => {
        page = parseInt(btn.dataset.page, 10);
        render();
      });
    });
  }

  function render() {
    let rows = allRows;
    if (searchTerm) {
      rows = rows.filter((tr) => tr.textContent.toLowerCase().includes(searchTerm));
    }
    if (sortCol != null) {
      rows = rows.slice().sort((a, b) => {
        const av = cellText(a, sortCol);
        const bv = cellText(b, sortCol);
        const an = parseFloat(av.replace(',', '.'));
        const bn = parseFloat(bv.replace(',', '.'));
        const cmp = !Number.isNaN(an) && !Number.isNaN(bn) ? an - bn : av.localeCompare(bv, 'it');
        return cmp * sortDir;
      });
    }

    const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (page > totalPages) page = totalPages;
    const start = (page - 1) * pageSize;
    const pageRows = rows.slice(start, start + pageSize);

    tbody.innerHTML = '';
    pageRows.forEach((tr) => tbody.appendChild(tr));
    if (window.EVUsage) EVUsage.wirePopovers(tbody);

    renderPagination(totalPages, rows.length);
  }

  render();
}
