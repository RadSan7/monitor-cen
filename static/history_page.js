// ── Historia — filtrowanie po typie, tekście i dacie ─────────────────────────

let _histType = 'all';

function setHistType(btn, type) {
  _histType = type;
  document.querySelectorAll('.hist-type-btn').forEach(b => {
    b.classList.toggle('active', b === btn);
  });
  histFilter();
}

function histFilter() {
  const query   = (document.getElementById('hist-search')?.value || '').toLowerCase().trim();
  const dateVal = document.getElementById('hist-date')?.value || 'all';
  const now     = Date.now();
  const cutoff  = dateVal === 'today' ? (now - 86400000) :
                  dateVal === '7d'    ? (now - 7 * 86400000) :
                  dateVal === '30d'   ? (now - 30 * 86400000) : 0;

  const items   = document.querySelectorAll('.hist-item');
  let visible   = 0;

  items.forEach(item => {
    const type    = item.dataset.type || '';
    const search  = item.dataset.search || '';
    const created = item.dataset.created || '';
    const createdMs = created ? new Date(created).getTime() : 0;

    let show = true;

    // Filter by type
    if (_histType !== 'all') {
      if (_histType === 'scrape_error') {
        // Show run items that have errors AND standalone error events
        show = type === 'scrape_error' ||
               (type === 'run' && item.querySelector('.badge.bg-danger') !== null);
      } else if (_histType === 'run') {
        show = type === 'run';
      } else {
        show = type === _histType;
      }
    }

    // Filter by search text
    if (show && query && !search.includes(query)) show = false;

    // Filter by date
    if (show && cutoff && createdMs < cutoff) show = false;

    item.classList.toggle('d-none', !show);
    if (show) visible++;
  });

  const noResults = document.getElementById('hist-no-results');
  if (noResults) noResults.classList.toggle('d-none', visible > 0);

  const countEl = document.getElementById('hist-count');
  if (countEl) countEl.textContent = visible + ' wpisów';
}
