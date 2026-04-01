// ── Clean product names ───────────────────────────────────────────────────────
function cleanProductName(name, brand) {
  const phrasesToRemove = [
    'Amplificateur',
    'Enceinte colonne',
    'Pack d\'enceintes',
    'Home-Cinema',
    'Hi-Fi',
    'HIFI',
  ];

  let cleaned = name;
  phrasesToRemove.forEach(phrase => {
    cleaned = cleaned.replace(new RegExp(phrase, 'gi'), '').trim();
  });
  cleaned = cleaned.replace(/\s+/g, ' ').trim();

  if (brand && !cleaned.toLowerCase().startsWith(brand.toLowerCase())) {
    cleaned = brand + ' ' + cleaned;
  }

  return cleaned;
}

// ── Badge 24h — pokaż dla produktów ze zmianą ceny w ostatnich 24h ───────────
function applyPriceChangeBadges() {
  const now = Date.now();
  document.querySelectorAll('.product-col').forEach(row => {
    const changedAt = row.dataset.priceChangedAt;
    if (!changedAt) return;
    const msAgo = now - new Date(changedAt).getTime();
    const badge = row.querySelector('.price-change-badge');
    if (badge) {
      badge.classList.toggle('d-none', msAgo > 86400000);
    }
  });
}

// ── Apply display names on page load ──────────────────────────────────────────
function applyDisplayNames() {
  document.querySelectorAll('.product-display-name').forEach(elem => {
    const cell = elem.closest('.product-name-cell');
    const productId = cell.dataset.id;
    const original  = cell.dataset.original;
    const brand     = cell.dataset.brand || '';

    const key = `product_name_v3_${productId}`;
    const stored = JSON.parse(localStorage.getItem(key) || 'null');
    if (stored && stored.brand === brand) {
      elem.textContent = stored.name;
    } else {
      const cleaned = cleanProductName(original, brand);
      elem.textContent = cleaned;
      localStorage.setItem(key, JSON.stringify({ name: cleaned, brand }));
    }
  });
}

// ── Editable product name (click pencil button) ────────────────────────────────
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.edit-name-btn');
  if (!btn) return;

  const cell = btn.closest('.product-name-cell');
  if (!cell || cell.querySelector('input')) return;

  const productId = cell.dataset.id;
  const displayElem = cell.querySelector('.product-display-name');
  const current = displayElem.textContent.trim();

  const input = document.createElement('input');
  input.type = 'text';
  input.value = current;
  input.className = 'form-control form-control-sm';
  input.style.cssText = 'width:100%; margin-bottom:0.25rem';

  displayElem.replaceWith(input);
  input.focus();
  input.select();

  const save = () => {
    const newName = input.value.trim() || current;
    const brand = cell.dataset.brand || '';
    localStorage.setItem(`product_name_v3_${productId}`, JSON.stringify({ name: newName, brand }));

    const span = document.createElement('span');
    span.className = 'product-display-name fw-bold mb-1 text-truncate';
    span.title = newName;
    span.textContent = newName;
    input.replaceWith(span);
  };

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') {
      const span = document.createElement('span');
      span.className = 'product-display-name fw-bold mb-1 text-truncate';
      span.title = current;
      span.textContent = current;
      input.replaceWith(span);
    }
  });
  input.addEventListener('blur', save, { once: true });
});

// ── Filter state ──────────────────────────────────────────────────────────────
const activeFilters      = new Set();
const activeStoreFilters = new Set();

function toggleFilter(name) {
  const colorMap = { favorite: 'btn-danger', dropship: 'btn-primary', changed: 'btn-warning', atlow: 'btn-success' };
  const btn = document.getElementById('btn-filter-' + name);
  if (activeFilters.has(name)) {
    activeFilters.delete(name);
    btn.classList.remove('active', 'btn-danger', 'btn-primary', 'btn-warning', 'btn-success');
    btn.classList.add('btn-outline-secondary');
  } else {
    activeFilters.add(name);
    btn.classList.remove('btn-outline-secondary');
    btn.classList.add('active', colorMap[name] || 'btn-secondary');
  }
  applyFilters();
}

function toggleStoreFilter(btn) {
  const s = btn.dataset.store;
  if (activeStoreFilters.has(s)) {
    activeStoreFilters.delete(s);
    btn.classList.remove('active');
  } else {
    activeStoreFilters.add(s);
    btn.classList.add('active');
  }
  applyFilters();
}

function applyFilters() {
  const query    = document.getElementById('search-input').value.toLowerCase().trim();
  const rows     = document.querySelectorAll('.product-col');
  const brandSel = document.getElementById('brand-select');
  const pMinEl   = document.getElementById('price-min');
  const pMaxEl   = document.getElementById('price-max');
  const brandVal = brandSel ? brandSel.value : '';
  const pMin     = parseFloat(pMinEl?.value) || 0;
  const pMax     = parseFloat(pMaxEl?.value) || Infinity;
  let visible    = 0;

  rows.forEach(row => {
    const name  = row.dataset.name  || '';
    const store = row.dataset.store || '';
    const brand = row.dataset.brand || '';
    const price = parseFloat(row.dataset.price) || 0;

    let show = true;
    if (query && !name.includes(query) && !store.includes(query) && !brand.includes(query)) show = false;
    if (activeFilters.has('favorite') && row.dataset.favorite !== '1') show = false;
    if (activeFilters.has('dropship') && row.dataset.dropship !== '1') show = false;
    if (activeFilters.has('changed')  && row.dataset.changed  !== '1') show = false;
    if (activeFilters.has('atlow')    && row.dataset.atlow    !== '1') show = false;
    if (activeStoreFilters.size && !activeStoreFilters.has(store))      show = false;
    if (brandVal && brand !== brandVal)                                  show = false;
    if (price && pMin && price < pMin)                                   show = false;
    if (price && pMax !== Infinity && price > pMax)                      show = false;

    row.classList.toggle('d-none', !show);
    if (show) visible++;
  });

  const noResults = document.getElementById('no-results');
  if (noResults) noResults.classList.toggle('d-none', visible > 0);

  const label = document.getElementById('count-label');
  if (label) label.textContent = visible + ' produkt' + pluralPL(visible);
}

function pluralPL(n) {
  if (n === 1) return '';
  if ([2,3,4].includes(n % 10) && ![12,13,14].includes(n % 100)) return 'y';
  return 'ów';
}

// ── Favorite toggle ───────────────────────────────────────────────────────────
async function toggleFavorite(id) {
  const res  = await fetch('/favorite/' + id, { method: 'POST' });
  const data = await res.json();
  if (!data.success) return;

  const row   = document.getElementById('row-' + id);
  const isNow = data.is_favorite;

  row.dataset.favorite = isNow ? '1' : '0';

  const btn = document.getElementById('fav-btn-' + id);
  if (btn) {
    btn.innerHTML = `<i class="bi bi-heart${isNow ? '-fill' : ''} me-2"></i>${isNow ? 'Usuń z ulubionych' : 'Ulubione'}`;
  }

  // Update grid-mode badge
  const badgeArea = row.querySelector('.badge-group');
  const favBadge  = row.querySelector('.favorite-badge');
  if (isNow && !favBadge) {
    const badge = document.createElement('span');
    badge.className = 'badge bg-danger favorite-badge';
    badge.innerHTML = '<i class="bi bi-heart-fill me-1"></i>';
    badgeArea?.appendChild(badge);
  } else if (!isNow && favBadge) {
    favBadge.remove();
  }
  // Update list-mode badge
  const indicators = row.querySelector('.list-filter-indicators');
  const listFavBadge = row.querySelector('.list-fav-badge');
  if (isNow && !listFavBadge) {
    const b = document.createElement('span');
    b.className = 'badge bg-danger list-fav-badge';
    b.innerHTML = '<i class="bi bi-heart-fill"></i>';
    indicators?.appendChild(b);
  } else if (!isNow && listFavBadge) {
    listFavBadge.remove();
  }

  applyFilters();
}

// ── Dropship toggle ───────────────────────────────────────────────────────────
async function toggleDropship(id) {
  const res  = await fetch('/dropship/' + id, { method: 'POST' });
  const data = await res.json();
  if (!data.success) return;

  const row   = document.getElementById('row-' + id);
  const isNow = data.is_dropship;

  row.dataset.dropship = isNow ? '1' : '0';

  // Update grid-mode badge
  const badgeArea = row.querySelector('.badge-group');
  const badgeEl   = row.querySelector('.dropship-badge');
  if (isNow && !badgeEl) {
    const badge = document.createElement('span');
    badge.className = 'badge bg-info dropship-badge';
    badge.innerHTML = '<i class="bi bi-rocket-fill me-1"></i>Dropship';
    badgeArea?.appendChild(badge);
  } else if (!isNow && badgeEl) {
    badgeEl.remove();
  }
  // Update list-mode badge
  const indicators = row.querySelector('.list-filter-indicators');
  const listDsBadge = row.querySelector('.list-dropship-badge');
  if (isNow && !listDsBadge) {
    const b = document.createElement('span');
    b.className = 'badge bg-info list-dropship-badge';
    b.innerHTML = '<i class="bi bi-rocket-fill me-1"></i>DS';
    indicators?.prepend(b);
  } else if (!isNow && listDsBadge) {
    listDsBadge.remove();
  }

  applyFilters();
}

// ── Update single ─────────────────────────────────────────────────────────────
async function updateProduct(id) {
  const icon = document.getElementById('spin-' + id);
  if (icon) icon.classList.add('spin');
  try {
    const res  = await fetch('/update/' + id, { method: 'POST' });
    const data = await res.json();
    if (data.success) { location.reload(); }
    else { alert('Błąd: ' + (data.error || 'Nieznany błąd')); }
  } catch (e) {
    alert('Błąd połączenia: ' + e);
  } finally {
    if (icon) icon.classList.remove('spin');
  }
}

// ── Update all — concurrent per-store ────────────────────────────────────────
// Każdy sklep sekwencyjnie (jeden produkt naraz), wszystkie sklepy równolegle.
async function updateAll() {
  const allRows = [...document.querySelectorAll('.product-col[id^="row-"]')];
  const total   = allRows.length;
  if (!total) return;

  // run_id grupuje wszystkie zdarzenia tego przebiegu w Historii
  const runId = 'run_' + Date.now();

  const btn          = document.getElementById('btn-update-all');
  const widget       = document.getElementById('update-progress');
  const progressText = document.getElementById('progress-text');
  const progressBar  = document.getElementById('progress-bar');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Aktualizuję…';
  widget.classList.remove('d-none');

  let done = 0, changed = 0, unavailable = 0, failed = 0;

  function onProductDone(data) {
    done++;
    if (data && data.success) {
      if (data.unavailable)        unavailable++;
      else if (data.price_changed) changed++;
    } else {
      failed++;
    }
    progressText.textContent = `${done} / ${total}`;
    progressBar.style.width  = `${(done / total) * 100}%`;
  }

  // Grupuj po sklepie
  const byStore = {};
  allRows.forEach(row => {
    const store = row.dataset.store;
    if (!byStore[store]) byStore[store] = [];
    byStore[store].push(row.id.replace('row-', ''));
  });

  // Każdy sklep: sekwencyjnie; wszystkie sklepy: równolegle
  const storePromises = Object.values(byStore).map(async ids => {
    for (const id of ids) {
      try {
        const res  = await fetch('/update/' + id, {
          method: 'POST',
          headers: { 'X-Run-Id': runId },
        });
        const data = await res.json();
        onProductDone(data);
      } catch (_) {
        onProductDone(null);
      }
    }
  });

  await Promise.all(storePromises);

  progressText.textContent = `${done} / ${total}`;
  progressBar.style.width  = '100%';
  progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated');

  setTimeout(() => widget.classList.add('d-none'), 1200);

  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-arrow-clockwise me-2"></i>Aktualizuj';

  const successCount = done - failed;
  let html = `<p class="fs-4 fw-bold mb-1">${successCount}<span class="fs-6 fw-normal text-muted">/${total}</span></p>`
           + `<p class="text-muted small mb-2">zaktualizowanych</p>`;

  const details = [];
  if (changed > 0)
    details.push(`<i class="bi bi-arrow-left-right me-1 text-warning"></i>${changed} produkt${changed === 1 ? '' : 'ów'} zmieniło ceny`);
  if (unavailable > 0)
    details.push(`<i class="bi bi-slash-circle me-1 text-secondary"></i>${unavailable} produkt${unavailable === 1 ? '' : 'ów'} niedostępny${unavailable > 1 ? 'ch' : ''}`);
  if (failed > 0)
    details.push(`<i class="bi bi-exclamation-circle me-1 text-danger"></i>${failed} błąd${failed > 1 ? 'ów' : ''}`);

  if (details.length)
    html += `<div class="text-muted small lh-lg">${details.join('<br>')}</div>`;

  document.getElementById('update-summary-body').innerHTML = html;

  const modal = new bootstrap.Modal(document.getElementById('update-summary-modal'));
  document.getElementById('update-summary-modal').addEventListener(
    'hidden.bs.modal', () => location.reload(), { once: true }
  );
  modal.show();
}

// ── Delete ───────────────────────────────────────────────────────────────────
document.addEventListener('click', async function(e) {
  const btn = e.target.closest('.delete-btn');
  if (!btn) return;
  const id = btn.dataset.id;
  if (!confirm('Usunąć produkt z listy?')) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const res  = await fetch('/delete/' + id, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      const row = document.getElementById('row-' + id);
      row.style.transition = 'opacity .25s';
      row.style.opacity = '0';
      setTimeout(() => { row.remove(); applyFilters(); }, 250);
    }
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-trash3 me-2"></i>Usuń';
  }
});

// ── Inline sale price edit ────────────────────────────────────────────────────
document.addEventListener('click', function(e) {
  const cell = e.target.closest('.sale-price-cell');
  if (!cell || cell.querySelector('input')) return;

  const id      = cell.dataset.id;
  const current = cell.querySelector('.fw-bold')?.textContent.trim().split('\u00a0')[0].replace(/[^\d.]/g, '') || '';

  const input = document.createElement('input');
  input.type      = 'number';
  input.step      = '0.01';
  input.min       = '0';
  input.value     = current;
  input.className = 'form-control form-control-sm';
  cell.innerHTML  = '';
  cell.appendChild(input);
  input.focus();
  input.select();

  const render = (sp) => {
    if (sp !== null && sp !== undefined) {
      cell.innerHTML = '<div class="stat-label">Cena w PL</div><div class="fw-bold text-primary">' +
        Number(sp).toFixed(2) + ' PLN</div>';
    } else {
      cell.innerHTML = '<div class="stat-label">Cena w PL</div><div class="fw-bold text-primary"><span class="text-muted small">+ dodaj</span></div>';
    }
  };

  const save = async () => {
    const val  = input.value.trim();
    const body = new FormData();
    if (val) body.append('sale_price', val);
    try {
      const res  = await fetch('/sale-price/' + id, {
        method: 'POST', body,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      const data = await res.json();
      if (data.success) render(data.sale_price);
    } catch { render(current || null); }
  };

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.removeEventListener('blur', save); render(current || null); }
  });
  input.addEventListener('blur', save, { once: true });
});

// ── Inline min price edit ────────────────────────────────────────────────────
document.addEventListener('click', function(e) {
  const cell = e.target.closest('.min-price-cell');
  if (!cell || cell.querySelector('input')) return;

  const id       = cell.dataset.id;
  const currency = cell.dataset.currency || 'EUR';
  const current  = cell.querySelector('.fw-bold')?.textContent.trim().split('\u00a0')[0].replace(/[^\d.]/g, '') || '';

  const input = document.createElement('input');
  input.type      = 'number';
  input.step      = '0.01';
  input.min       = '0';
  input.value     = current;
  input.className = 'form-control form-control-sm';
  cell.innerHTML  = '';
  cell.appendChild(input);
  input.focus();
  input.select();

  const render = (mp) => {
    const row = document.getElementById('row-' + id);
    const priceSpan = row?.querySelector('[id^="price-"]');
    const currentPrice = priceSpan ? parseFloat(priceSpan.textContent.trim().split('\u00a0')[0]) : null;
    const isMinCurrent = currentPrice !== null && currentPrice === parseFloat(mp);

    if (mp !== null && mp !== undefined && mp !== '') {
      const colorClass = isMinCurrent ? 'text-success' : '';
      cell.innerHTML = '<div class="stat-label">Min. Hist.</div><div class="fw-bold ' + colorClass + '">' +
        Number(mp).toFixed(2) + ' ' + currency + '</div>';
    } else {
      cell.innerHTML = '<div class="stat-label">Min. Hist.</div><div class="fw-bold">—</div>';
    }
  };

  const save = async () => {
    const val  = input.value.trim();
    const body = new FormData();
    if (val) body.append('min_price', val);
    try {
      const res  = await fetch('/min-price/' + id, {
        method: 'POST', body,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      const data = await res.json();
      if (data.success) render(data.min_price);
    } catch { render(current || null); }
  };

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.removeEventListener('blur', save); render(current || null); }
  });
  input.addEventListener('blur', save, { once: true });
});

// ── Dropdown z-index fix in list view ────────────────────────────────────────
document.addEventListener('shown.bs.dropdown', e => {
  e.target.closest('.product-col')?.classList.add('dropdown-open');
});
document.addEventListener('hidden.bs.dropdown', e => {
  e.target.closest('.product-col')?.classList.remove('dropdown-open');
});

// ── View toggle (grid / list) ─────────────────────────────────────────────────
function setView(mode) {
  const grid    = document.getElementById('products-grid');
  const btnGrid = document.getElementById('btn-view-grid');
  const btnList = document.getElementById('btn-view-list');
  if (!grid) return;

  if (mode === 'list') {
    grid.classList.add('list-view');
    btnGrid?.classList.remove('active');
    btnList?.classList.add('active');
  } else {
    grid.classList.remove('list-view');
    btnGrid?.classList.add('active');
    btnList?.classList.remove('active');
  }
  localStorage.setItem('productView', mode);
}

// ── Grok search for audio deals ────────────────────────────────────────────────
async function searchGrok() {
  const btn = document.getElementById('btn-grok');
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Otwieranie Grok...';

  try {
    const response = await fetch('/grok-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    const data = await response.json();
    const prompt = data.prompt || '';

    const grokWindow = window.open('https://grok.com/', '_blank');

    if (!grokWindow) {
      alert('Nie mogę otworzyć Grok. Sprawdź blokowanie pop-upów.');
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-robot me-2"></i>Grok';
      return;
    }

    setTimeout(() => {
      try {
        grokWindow.postMessage({ type: 'GROK_PROMPT', prompt }, '*');
      } catch (e) {}
    }, 2000);

    const modalBody = document.getElementById('grok-prompt-body');
    if (modalBody) {
      modalBody.innerHTML = `
        <div class="alert alert-info mb-3">
          <strong>Okno Grok się otworzyło!</strong><br>
          Skopiuj poniższy prompt jeśli nie pojawił się automatycznie:
        </div>
        <div class="bg-light p-3 rounded mb-3 small" style="font-family:monospace; max-height:200px; overflow-y:auto;">
          ${escapeHtml(prompt)}
        </div>
        <button class="btn btn-sm btn-primary w-100" onclick="copyToClipboard(\`${escapeHtml(prompt)}\`)">
          <i class="bi bi-clipboard me-2"></i>Skopiuj prompt
        </button>
      `;
      new bootstrap.Modal(document.getElementById('grok-prompt-modal')).show();
    }

    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-robot me-2"></i>Grok';
  } catch (error) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-robot me-2"></i>Grok';
    alert('Błąd: ' + error.message);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    alert('Prompt skopiowany do schowka!');
  });
}

// ── Initialize on page load ──────────────────────────────────────────────────
function _initPage() {
  applyDisplayNames();
  applyPriceChangeBadges();
  setView(localStorage.getItem('productView') || 'grid');
  // Auto-start update jeśli przekierowano z innej strony przez ?update=1
  const params = new URLSearchParams(window.location.search);
  if (params.get('update') === '1') {
    history.replaceState({}, '', '/');
    setTimeout(updateAll, 300);
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initPage);
} else {
  _initPage();
}
