/**
 * Wizard Overlay — wstrzykiwany przez Playwright do strony sklepu.
 * Zmienne __SESSION_ID__ i __FLASK_PORT__ są podstawiane przez wizard.py.
 */
(function () {
  if (window.__wizardOverlayActive) return;
  window.__wizardOverlayActive = true;

  const SESSION_ID = '__SESSION_ID__';
  const BASE_URL   = 'http://localhost:__FLASK_PORT__';

  const FIELDS = ['name', 'brand', 'price'];
  const LABELS = {
    name:  'NAZWĘ PRODUKTU',
    brand: 'MARKĘ / PRODUCENTA',
    price: 'CENĘ',
  };

  let currentIdx = 0;
  const captured = {};

  // ── Panel ──────────────────────────────────────────────────────────────────
  const style = document.createElement('style');
  style.textContent = `
    #__wiz_panel * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, Inter, sans-serif !important; }
    #__wiz_panel strong { font-weight: 700; }
  `;
  document.head.appendChild(style);

  const panel = document.createElement('div');
  panel.id = '__wiz_panel';
  panel.setAttribute('style', [
    'position:fixed', 'top:16px', 'right:16px', 'z-index:2147483647',
    'width:310px', 'background:rgba(10,10,22,0.93)', 'color:#fff',
    'border-radius:18px', 'padding:20px 22px',
    'font-size:14px', 'line-height:1.55',
    'box-shadow:0 8px 40px rgba(0,0,0,0.55)',
    'border:1px solid rgba(255,255,255,0.13)',
    'backdrop-filter:blur(14px)',
  ].join(';'));

  panel.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
      <span style="font-size:22px">🔍</span>
      <strong style="font-size:15px;letter-spacing:-0.3px">Wizard integracji</strong>
    </div>
    <div id="__wiz_badge" style="
      display:inline-block;background:#0070f3;color:#fff;
      border-radius:8px;padding:2px 11px;font-size:12px;font-weight:600;
      margin-bottom:12px;letter-spacing:0.2px
    ">Krok 1 / 3</div>
    <div id="__wiz_instr" style="margin-bottom:14px;font-size:14px">
      Kliknij element zawierający
      <strong id="__wiz_lbl" style="color:#fbbf24">NAZWĘ PRODUKTU</strong>
    </div>
    <div id="__wiz_list" style="font-size:12px;opacity:0.75;min-height:20px"></div>
    <div id="__wiz_done" style="display:none;text-align:center;padding:12px 0">
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
      // 1. id — globalnie unikalne
      if (cur.id) {
        parts.unshift('#' + CSS.escape(cur.id));
        break;
      }

      const tag = cur.tagName.toLowerCase();

      // 2. tag + klasy — szukamy najmniejszego zestawu dającego dokładnie 1 wynik
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

      // 3. nth-of-type względem rodzica
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

  // ── Aktualizacja UI ────────────────────────────────────────────────────────
  function refreshCaptured() {
    const div = document.getElementById('__wiz_list');
    if (!div) return;
    const fieldNames = { name: 'Nazwa', brand: 'Marka', price: 'Cena' };
    div.innerHTML = Object.entries(captured)
      .map(([k, v]) => `✅ <strong>${fieldNames[k] || k}:</strong> ${v.preview.slice(0, 45)}`)
      .join('<br>');
  }

  function advanceStep() {
    const badge = document.getElementById('__wiz_badge');
    const lbl   = document.getElementById('__wiz_lbl');
    if (badge) badge.textContent = `Krok ${currentIdx + 1} / 3`;
    if (lbl)   lbl.textContent   = LABELS[FIELDS[currentIdx]];
  }

  function showDone() {
    const instr = document.getElementById('__wiz_instr');
    const badge = document.getElementById('__wiz_badge');
    const done  = document.getElementById('__wiz_done');
    if (instr) instr.style.display = 'none';
    if (badge) badge.style.display = 'none';
    if (done)  done.style.display  = 'block';
    document.removeEventListener('mouseover', onOver, true);
    document.removeEventListener('click',     onClick, true);
    hideHL();
  }

  // ── Zdarzenia ──────────────────────────────────────────────────────────────
  function onOver(e) {
    const el = e.target;
    if (panel.contains(el) || el === panel) return;
    showHL(el);
  }

  function onClick(e) {
    const el = e.target;
    if (panel.contains(el) || el === panel) return;

    e.preventDefault();
    e.stopImmediatePropagation();

    const field    = FIELDS[currentIdx];
    const selector = computeSelector(el);
    const preview  = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 200);

    captured[field] = { selector, preview };
    refreshCaptured();

    fetch(BASE_URL + '/integrations/capture/' + SESSION_ID, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ field, selector, preview }),
    }).catch(() => {});

    currentIdx++;
    if (currentIdx >= FIELDS.length) {
      showDone();
    } else {
      advanceStep();
    }
  }

  document.addEventListener('mouseover', onOver,   true);
  document.addEventListener('click',     onClick,  true);
})();
