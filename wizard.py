"""
Wizard integracji nowych sklepów.
Zarządza sesjami Playwright: otwiera widoczne okno Chromium,
wstrzykuje overlay JS do wyboru selektorów, testuje scraping,
zapisuje konfigurację do stores.json.
"""
import json
import re
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page

STORES_JSON_PATH = Path(__file__).parent / 'stores.json'
OVERLAY_JS_PATH  = Path(__file__).parent / 'static' / 'wizard_overlay.js'
SESSION_TTL      = 30 * 60  # 30 minut

WIZARD_FIELDS = ['name', 'brand', 'price']

NEXT_STEP = {
    'awaiting_name':  'awaiting_brand',
    'awaiting_brand': 'awaiting_price',
    'awaiting_price': 'complete',
}

_sessions: dict[str, 'WizardSession'] = {}
_lock = threading.Lock()

_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)


@dataclass
class WizardSession:
    session_id: str
    url: str
    domain: str
    pw: object          # sync_playwright() instance
    browser: Browser
    page: Page
    step: str = 'awaiting_name'
    captured: dict = field(default_factory=dict)
    html_cache: Optional[str] = None
    created_at: float = field(default_factory=time.time)


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def _cleanup_old_sessions():
    now = time.time()
    stale = [sid for sid, s in _sessions.items() if now - s.created_at > SESSION_TTL]
    for sid in stale:
        close_session(sid)


def start_session(url: str, flask_port: int = 5000) -> str:
    """Uruchamia Playwright, otwiera URL, wstrzykuje overlay. Zwraca session_id."""
    _cleanup_old_sessions()

    from urllib.parse import urlparse
    domain = urlparse(url).netloc.removeprefix('www.')

    session_id = uuid.uuid4().hex

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--window-size=1280,900'],
    )
    context = browser.new_context(
        user_agent=_UA,
        locale='fr-FR',
        viewport={'width': 1280, 'height': 900},
    )
    context.add_init_script(
        'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    )
    page = context.new_page()
    page.goto(url, wait_until='domcontentloaded', timeout=30_000)
    page.wait_for_timeout(2_000)

    # Wstrzyknięcie overlaya z podstawionymi zmiennymi
    overlay_js = OVERLAY_JS_PATH.read_text(encoding='utf-8')
    overlay_js = overlay_js.replace('__SESSION_ID__', session_id)
    overlay_js = overlay_js.replace('__FLASK_PORT__', str(flask_port))
    page.evaluate(overlay_js)

    sess = WizardSession(
        session_id=session_id,
        url=url,
        domain=domain,
        pw=pw,
        browser=browser,
        page=page,
    )
    with _lock:
        _sessions[session_id] = sess

    return session_id


def close_session(session_id: str):
    with _lock:
        sess = _sessions.pop(session_id, None)
    if sess:
        try:
            sess.browser.close()
        except Exception:
            pass
        try:
            sess.pw.stop()
        except Exception:
            pass


# ── Stan sesji ─────────────────────────────────────────────────────────────────

def get_session(session_id: str) -> Optional[WizardSession]:
    return _sessions.get(session_id)


def get_status(session_id: str) -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {'error': 'Session not found'}

    try:
        alive = sess.browser.is_connected()
    except Exception:
        alive = False

    if not alive and sess.step not in ('complete', 'error'):
        with _lock:
            if session_id in _sessions:
                _sessions[session_id].step = 'error'
        sess.step = 'error'

    return {
        'step': sess.step,
        'captured': sess.captured,
        'browser_alive': alive,
        'domain': sess.domain,
    }


def capture_field(session_id: str, field: str, selector: str, preview: str) -> dict:
    """Wywoływane przez wstrzyknięty JS — zapisuje selektor dla pola."""
    with _lock:
        sess = _sessions.get(session_id)
        if not sess:
            return {'ok': False, 'error': 'Session not found'}
        if field not in WIZARD_FIELDS:
            return {'ok': False, 'error': f'Nieznane pole: {field}'}

        sess.captured[field] = {'selector': selector, 'preview': preview}
        next_step = NEXT_STEP.get(sess.step, 'complete')
        sess.step = next_step

        # Cache HTML gdy wszystkie pola zebrane
        if next_step == 'complete':
            try:
                sess.html_cache = sess.page.content()
            except Exception:
                pass

    return {'ok': True, 'next_step': next_step}


# ── Test scrapingu ─────────────────────────────────────────────────────────────

def test_scrape(session_id: str, price_type: str, vat_rate: int, currency: str) -> dict:
    """Testuje scraping z zebranymi selektorami. Zwraca wyekstrahowane dane."""
    sess = _sessions.get(session_id)
    if not sess:
        return {'ok': False, 'error': 'Session not found'}

    html = sess.html_cache
    if not html:
        try:
            html = sess.page.content()
        except Exception as e:
            return {'ok': False, 'error': f'Nie można pobrać HTML: {e}'}

    soup = BeautifulSoup(html, 'lxml')
    extracted = {}

    for field_name in WIZARD_FIELDS:
        info = sess.captured.get(field_name)
        if not info:
            continue
        sel = info['selector']
        el = soup.select_one(sel)
        if el is None:
            return {'ok': False, 'error': f'Selektor "{sel}" nie znalazł żadnego elementu na stronie'}
        extracted[field_name] = el.get_text(strip=True)

    # Parsowanie ceny
    raw_price = extracted.get('price', '')
    price = _parse_price(raw_price, price_type, vat_rate)

    return {
        'ok': True,
        'result': {
            'name':     extracted.get('name', ''),
            'brand':    extracted.get('brand', ''),
            'price':    price,
            'currency': currency,
        },
    }


def _parse_price(raw: str, price_type: str, vat_rate: int) -> Optional[float]:
    """Wyciąga liczbę z tekstu ceny i opcjonalnie przelicza brutto→netto."""
    # Wyciągnij pierwszą sekwencję cyfr z separatorami
    m = re.search(r'[\d\s\u00a0\u202f]+[,.]?\d*', raw)
    if not m:
        return None
    s = m.group().replace(' ', '').replace('\u00a0', '').replace('\u202f', '')
    # Normalizacja separatorów dziesiętnych
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        price = float(s)
    except ValueError:
        return None
    if price_type == 'gross' and vat_rate:
        price = round(price / (1 + vat_rate / 100), 2)
    return price


# ── Zapis konfiguracji ─────────────────────────────────────────────────────────

def save_store(session_id: str, display_name: str, price_type: str,
               vat_rate: int, currency: str) -> dict:
    """Zapisuje sklep do stores.json i przeładowuje konfigurację w scraper.py."""
    sess = _sessions.get(session_id)
    if not sess:
        return {'ok': False, 'error': 'Session not found'}

    if STORES_JSON_PATH.exists():
        data = json.loads(STORES_JSON_PATH.read_text(encoding='utf-8'))
    else:
        data = {'version': 1, 'stores': []}

    # Nadpisz jeśli domena już istnieje
    data['stores'] = [s for s in data['stores'] if s['domain'] != sess.domain]
    data['stores'].append({
        'domain':       sess.domain,
        'display_name': display_name,
        'selectors':    {k: v['selector'] for k, v in sess.captured.items()},
        'price_type':   price_type,
        'vat_rate':     vat_rate,
        'currency':     currency,
        'created_at':   datetime.now().isoformat(timespec='seconds'),
    })

    STORES_JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    import scraper
    scraper.reload_stores()

    close_session(session_id)
    return {'ok': True}
