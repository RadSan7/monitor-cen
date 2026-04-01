/**
 * Wizard Overlay — wstrzykiwany przez Playwright do strony sklepu.
 * Zmienne __SESSION_ID__ i __FLASK_PORT__ są podstawiane przez wizard.py.
 *
 * Przepływ:
 *  1. Kliknij "Wybierz" przy danym polu → aktywuje tryb zaznaczania
 *  2. Najedź kursorem na element → niebieskie podświetlenie
 *  3. Kliknij element → zapisuje selektor, wyświetla podgląd, wychodzi z trybu
 *  4. Możesz kliknąć "Zmień" aby ponownie wybrać, lub "Pomiń" dla marki
 *  5. Gdy nazwa + cena wybrane → pojawia się "Gotowe" → kliknij i wróć do Monitora
 */
(function () {
  if (window.__wizardOverlayActive) return;
  window.__wizardOverlayActive = true;

  const SESSION_ID = '__SESSION_ID__';
  const BASE_URL   = 'http://localhost:__FLASK_PORT__';

  const FIELDS = ['name', 'brand', 'price', 'thumbnail'];
  const LABELS = { name: 'Nazwa produktu', brand: 'Marka / Producent', price: 'Cena', thumbnail: 'Zdjęcie produktu' };
  const COLORS = { name: '#fbbf24', brand: '#c4b5fd', price: '#86efac', thumbnail: '#67e8f9' };

  const captured = {};
  let selectionMode = null; // null lub nazwa pola w trybie zaznaczania

  // ── Warmup ping — wywołuje dialog uprawnień macOS przed pierwszym kliknięciem
  fetch(BASE_URL + '/integrations/ping', { method: 'POST' }).catch(() => {});

  // ── Style ─────────────────────────────────────────────────────────────────
  const style = document.createElement('style');
  style.textContent = `
    #__wiz_panel * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, Inter, sans-serif !important; }
    #__wiz_panel strong { font-weight: 700; }
    .wiz-field-row {
      display: flex; align-items: center; gap: 8px;
      border-radius: 10px; padding: 8px 10px; margin-bottom: 6px;
      border: 1.5px solid rgba(255,255,255,0.1);
      transition: border-color 0.2s;
    }
    .wiz-field-row.captured { border-color: rgba(34,197,94,0.6); }
    .wiz-btn {
      background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
      color: #fff; border-radius: 6px; padding: 3px 10px;
      font-size: 12px; cursor: pointer; flex-shrink: 0;
    }
    .wiz-btn:hover { background: rgba(255,255,255,0.22); }
  `;
  document.head.appendChild(style);

  // ── Panel ─────────────────────────────────────────────────────────────────
  const panel = document.createElement('div');
  panel.id = '__wiz_panel';
  panel.setAttribute('style', [
    'position:fixed', 'top:16px', 'right:16px', 'z-index:2147483647',
    'width:320px', 'background:rgba(10,10,22,0.95)', 'color:#fff',
    'border-radius:18px', 'padding:20px 22px',
    'font-size:14px', 'line-height:1.55',
    'box-shadow:0 8px 40px rgba(0,0,0,0.6)',
    'border:1px solid rgba(255,255,255,0.13)',
    'backdrop-filter:blur(14px)',
  ].join(';'));

  const fieldRowsHtml = FIELDS.map(f => `
    <div class="wiz-field-row" id="__wfr_${f}">
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;font-weight:700;color:${COLORS[f]};margin-bottom:1px">${LABELS[f]}</div>
        <div id="__wprev_${f}" style="font-size:11px;opacity:0.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">nie wybrano</div>
      </div>
      <div style="display:flex;gap:4px;flex-shrink:0">
        ${(f === 'brand' || f === 'thumbnail') ? `<button class="wiz-btn" id="__wskip_${f}">Pomiń</button>` : ''}
        <button class="wiz-btn" id="__wbtn_${f}">Wybierz</button>
      </div>
    </div>
  `).join('');

  panel.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span style="font-size:22px">🔍</span>
      <strong style="font-size:15px;letter-spacing:-0.3px">Wizard integracji</strong>
    </div>
    <div id="__wiz_hint" style="font-size:11px;opacity:0.5;margin-bottom:14px">
      Kliknij "Wybierz" przy polu → kliknij element na stronie
    </div>

    ${fieldRowsHtml}

    <div id="__wiz_mode" style="display:none;margin:10px 0;
      background:rgba(0,112,243,0.18);border:1px solid rgba(0,112,243,0.5);
      border-radius:10px;padding:8px 12px">
      <div style="font-size:12px;font-weight:700;margin-bottom:3px">🎯 Tryb zaznaczania aktywny</div>
      <div id="__wiz_mlbl" style="font-size:11px;opacity:0.75;margin-bottom:8px">—</div>
      <button class="wiz-btn" id="__wiz_cancel_sel" style="width:100%;text-align:center">
        ✕ Anuluj zaznaczanie
      </button>
    </div>

    <div id="__wiz_done_wrap" style="display:none;margin-top:12px">
      <button id="__wiz_done" style="
        width:100%;background:#22c55e;border:none;color:#fff;
        border-radius:10px;padding:9px 12px;font-size:13px;font-weight:700;cursor:pointer">
        ✅ Gotowe — wróć do Monitora
      </button>
    </div>

    <div id="__wiz_complete" style="display:none;text-align:center;padding:16px 0">
      <div style="font-size:30px;margin-bottom:8px">✅</div>
      <strong style="font-size:15px">Gotowe!</strong><br>
      <span style="opacity:0.75;font-size:13px">Wróć do okna Monitora Cen</span>
    </div>
  `;
  document.body.appendChild(panel);

  // ── Ramka podświetlenia ────────────────────────────────────────────────────
  const hl = document.createElement('div');
  hl.setAttribute('style', [
    'position:fixed', 'pointer-events:none', 'z-index:2147483646',
    'border:3px solid #0070f3', 'border-radius:5px',
    'background:rgba(0,112,243,0.07)',
    'transition:top 0.06s,left 0.06s,width 0.06s,height 0.06s',
    'display:none',
  ].join(';'));
  document.body.appendChild(hl);

  function showHL(el) {
    const r = el.getBoundingClientRect();
    hl.style.display = 'block';
    hl.style.top     = r.top    + 'px';
    hl.style.left    = r.left   + 'px';
    hl.style.width   = r.width  + 'px';
    hl.style.height  = r.height + 'px';
  }
  function hideHL() { hl.style.display = 'none'; }

  // ── Obliczanie selektora CSS ───────────────────────────────────────────────
  function computeSelector(el) {
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && cur !== document.documentElement) {
      if (cur.id) {
        parts.unshift('#' + CSS.escape(cur.id));
        break;
      }
      const tag = cur.tagName.toLowerCase();
      const cls = [...cur.classList].filter(c => c && !/^\d/.test(c));
      let matched = false;
      for (let n = 1; n <= cls.length; n++) {
        const sel = tag + '.' + cls.slice(0, n).map(c => CSS.escape(c)).join('.');
        if (document.querySelectorAll(sel).length === 1) {
          parts.unshift(sel);
          matched = true;
          break;
        }
      }
      if (matched) break;
      const sibs = cur.parentElement
        ? [...cur.parentElement.children].filter(s => s.tagName === cur.tagName)
        : [];
      const part = sibs.length > 1
        ? `${tag}:nth-of-type(${sibs.indexOf(cur) + 1})`
        : tag;
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(' > ') || el.tagName.toLowerCase();
  }

  // ── Tryb zaznaczania ──────────────────────────────────────────────────────
  function onOver(e) {
    const el = e.target;
    if (panel.contains(el) || el === panel || el === hl) return;
    showHL(el);
  }

  function onClick(e) {
    const el = e.target;
    if (panel.contains(el) || el === panel) return;

    e.preventDefault();
    e.stopImmediatePropagation();

    const field    = selectionMode;
    const selector = computeSelector(el);
    let preview;
    if (field === 'thumbnail') {
      const imgEl = el.tagName === 'IMG' ? el : el.querySelector('img');
      preview = imgEl
        ? (imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || imgEl.getAttribute('data-lazy-src') || selector)
        : selector;
    } else {
      preview = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 200);
    }

    captured[field] = { selector, preview };
    markField(field, preview.slice(0, 50) || selector);

    fetch(BASE_URL + '/integrations/capture/' + SESSION_ID, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ field, selector, preview }),
    }).catch(() => {});

    exitSelectionMode();
    updateDoneButton();
  }

  function enterSelectionMode(field) {
    selectionMode = field;
    document.getElementById('__wiz_mode').style.display   = 'block';
    document.getElementById('__wiz_mlbl').textContent     = 'Wybierasz: ' + LABELS[field];
    document.getElementById('__wiz_done_wrap').style.display = 'none';
    document.addEventListener('mouseover', onOver, true);
    document.addEventListener('click',     onClick,  true);
  }

  function exitSelectionMode() {
    selectionMode = null;
    document.getElementById('__wiz_mode').style.display = 'none';
    hideHL();
    document.removeEventListener('mouseover', onOver, true);
    document.removeEventListener('click',     onClick,  true);
  }

  function markField(field, previewText) {
    const prevEl = document.getElementById('__wprev_' + field);
    const rowEl  = document.getElementById('__wfr_'   + field);
    const btnEl  = document.getElementById('__wbtn_'  + field);
    if (prevEl) prevEl.textContent = previewText;
    if (rowEl)  rowEl.classList.add('captured');
    if (btnEl)  btnEl.textContent = 'Zmień';
  }

  function updateDoneButton() {
    const wrap = document.getElementById('__wiz_done_wrap');
    if (wrap) wrap.style.display = (captured['name'] && captured['price']) ? 'block' : 'none';
  }

  // ── Przyciski "Wybierz" ────────────────────────────────────────────────────
  FIELDS.forEach(f => {
    document.getElementById('__wbtn_' + f).addEventListener('click', function (e) {
      e.stopPropagation();
      if (selectionMode) exitSelectionMode();
      enterSelectionMode(f);
    });
  });

  // ── Przyciski "Pomiń" (marka, zdjęcie) ────────────────────────────────────
  [{ f: 'brand', label: '(brak marki)' }, { f: 'thumbnail', label: '(brak zdjęcia)' }].forEach(({ f, label }) => {
    document.getElementById('__wskip_' + f).addEventListener('click', function (e) {
      e.stopPropagation();
      if (selectionMode === f) exitSelectionMode();
      captured[f] = { selector: '', preview: label };
      markField(f, label);
      fetch(BASE_URL + '/integrations/capture/' + SESSION_ID, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ field: f, selector: '', preview: label }),
      }).catch(() => {});
      updateDoneButton();
    });
  });

  // ── Przycisk "Anuluj zaznaczanie" ─────────────────────────────────────────
  document.getElementById('__wiz_cancel_sel').addEventListener('click', function (e) {
    e.stopPropagation();
    exitSelectionMode();
    updateDoneButton();
  });

  // ── Przycisk "Gotowe" ─────────────────────────────────────────────────────
  document.getElementById('__wiz_done').addEventListener('click', function (e) {
    e.stopPropagation();
    fetch(BASE_URL + '/integrations/complete/' + SESSION_ID, { method: 'POST' }).catch(() => {});

    document.getElementById('__wiz_done_wrap').style.display = 'none';
    document.getElementById('__wiz_hint').style.display      = 'none';
    FIELDS.forEach(f => {
      const r = document.getElementById('__wfr_' + f);
      if (r) r.style.display = 'none';
    });
    document.getElementById('__wiz_complete').style.display = 'block';
  });
})();
