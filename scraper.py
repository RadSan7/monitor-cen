"""
Scraper for fnacpro.com, homecinesolutions.fr and dynamically-configured stores.

Strategy:
  1. Try curl_cffi (fast, no window) — works for homecinesolutions.fr
  2. If blocked (403/empty), fall back to Playwright headless=False
     — works for fnacpro.com which detects headless Chromium
  3. CSS-selector stores (added via wizard) use BeautifulSoup after fetch.
"""

import json
import pathlib
import queue as _queue
import re
import subprocess
import sys
import threading
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SUPPORTED_STORES = {
    'fnacpro.com': 'Fnac Pro',
    'homecinesolutions.fr': 'HomeCine Solutions',
}

# Dynamicznie ładowane z stores.json (sklepy dodane przez wizard)
_css_store_configs: dict[str, dict] = {}
_STORES_JSON = pathlib.Path(__file__).parent / 'stores.json'


def reload_stores():
    """Ładuje/przeładowuje konfiguracje CSS-selector z stores.json."""
    global _css_store_configs
    if not _STORES_JSON.exists():
        _css_store_configs = {}
        return
    try:
        data = json.loads(_STORES_JSON.read_text(encoding='utf-8'))
        _css_store_configs = {s['domain']: s for s in data.get('stores', [])}
    except Exception:
        _css_store_configs = {}


reload_stores()

_UNAVAILABLE_AVAILABILITY = {
    'http://schema.org/OutOfStock',
    'https://schema.org/OutOfStock',
    'OutOfStock',
    'http://schema.org/Discontinued',
    'https://schema.org/Discontinued',
    'Discontinued',
}

_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)

def detect_store(url: str) -> str:
    # JSON-LD sklepy mają priorytet (hardcoded)
    for domain, name in SUPPORTED_STORES.items():
        if domain in url:
            return name
    # CSS-selector sklepy z wizard
    for domain, config in _css_store_configs.items():
        if domain in url:
            return config['display_name']
    all_domains = list(SUPPORTED_STORES.keys()) + list(_css_store_configs.keys())
    raise ValueError(
        f"Nieobsługiwany sklep. Obsługiwane: {', '.join(all_domains)}"
    )


def _parse_json_ld(html: str) -> dict:
    """Find the first JSON-LD <script> block with @type == Product."""
    soup = BeautifulSoup(html, 'lxml')
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            if data.get('@type') == 'Product':
                return data
        except (json.JSONDecodeError, AttributeError):
            continue
    raise ValueError("Nie znaleziono danych produktu (JSON-LD) na stronie")


def _extract_product(data: dict, url: str, store: str) -> dict:
    name = data.get('name') or 'Nieznany produkt'

    images = data.get('image', [])
    thumbnail = images[0] if isinstance(images, list) and images else (images or None)

    offers = data.get('offers', {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    availability = offers.get('availability', '')
    raw_price = offers.get('price')

    if availability in _UNAVAILABLE_AVAILABILITY or raw_price is None:
        price = None
    else:
        price = float(raw_price)
        # HomeCine podaje ceny brutto (TTC) — przeliczamy na netto (HT) dzieląc przez 1.20
        if store == 'HomeCine Solutions':
            price = round(price / 1.20, 2)

    brand_data = data.get('brand', {})
    brand = (brand_data.get('name', '') if isinstance(brand_data, dict) else '') or ''

    return {
        'name':          name,
        'url':           url,
        'store':         store,
        'thumbnail_url': thumbnail,
        'price':         price,
        'currency':      offers.get('priceCurrency', 'EUR'),
        'brand':         brand,
    }


def _fetch_curl(url: str) -> str | None:
    """Return HTML via curl_cffi or None if blocked/errored."""
    try:
        r = cffi_requests.get(url, impersonate='chrome', timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


# ── Persistent Playwright browsers — dedicated worker threads ─────────────────
#
# Playwright sync API używa greenletów związanych z wątkiem tworzącym instancję.
# Wywołanie z innego wątku Flaska → "cannot switch to a different thread (exited)".
# Rozwiązanie: jeden długożyjący wątek-demon per browser; komunikacja przez kolejki.

_BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--window-position=9999,9999',   # poza ekranem — prawy dolny róg
    '--window-size=1280,800',
]


def _get_frontmost_app() -> str:
    """Zwraca nazwę aktualnie aktywnej aplikacji (macOS)."""
    if sys.platform != 'darwin':
        return ''
    try:
        r = subprocess.run(
            ['osascript', '-e',
             'tell application "System Events" to get name of first process whose frontmost is true'],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip()
    except Exception:
        return ''


def _fix_focus_after_launch(prev_app: str):
    """Ukryj wszystkie procesy Chromium i przywróć focus — jedno wywołanie osascript."""
    if sys.platform != 'darwin':
        return
    # delay 0.8 w AppleScript czeka aż macOS zmieni frontmost; wszystko w jednym
    # procesie żeby nie było race-condition między hide a activate
    activate_line = f'tell application "{prev_app}" to activate' if prev_app else ''
    script = f'''
delay 0.8
tell application "System Events"
    repeat with proc in (every process whose name contains "Chromium")
        set visible of proc to false
    end repeat
end tell
{activate_line}
'''
    try:
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=4)
    except Exception:
        pass


def _do_fetch_in_browser(browser, url: str) -> str:
    """Wykonuje fetch w podanym browserze (musi być wywołane z wątku właściciela)."""
    context = browser.new_context(
        user_agent=_UA,
        locale='fr-FR',
        viewport={'width': 1280, 'height': 800},
    )
    context.add_init_script(
        'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    )
    page = context.new_page()
    try:
        cdp = context.new_cdp_session(page)
        info = cdp.send('Browser.getWindowForTarget')
        cdp.send('Browser.setWindowBounds', {
            'windowId': info['windowId'],
            'bounds': {'windowState': 'minimized'},
        })
    except Exception:
        pass
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30_000)
        page.wait_for_timeout(2_000)
    except PlaywrightTimeout:
        context.close()
        raise ConnectionError("Strona nie załadowała się w czasie 30 s. Sprawdź połączenie.")
    html = page.content()
    context.close()
    return html


def _launch_browser(pw, headless: bool):
    """Uruchamia browser i ukrywa jego okno, nie kradnąc focusu."""
    prev_app = _get_frontmost_app()
    browser = pw.chromium.launch(headless=headless, args=_BROWSER_ARGS)
    # _fix_focus_after_launch sam czeka (delay 0.8) i robi hide + activate atomowo
    threading.Thread(target=_fix_focus_after_launch, args=(prev_app,), daemon=True).start()
    return browser


def _browser_worker(task_queue: '_queue.Queue', headless: bool = False):
    """Wątek-demon zarządzający jednym trwałym browserem Playwright."""
    pw = sync_playwright().start()
    browser = _launch_browser(pw, headless)
    while True:
        url, result_q = task_queue.get()
        try:
            html = _do_fetch_in_browser(browser, url)
            result_q.put(('ok', html))
        except Exception as exc:
            # Jeśli browser padł, spróbuj go zrestartować
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass
            try:
                pw = sync_playwright().start()
                browser = _launch_browser(pw, headless)
                html = _do_fetch_in_browser(browser, url)
                result_q.put(('ok', html))
            except Exception as exc2:
                result_q.put(('err', exc2))


def _make_browser_worker(headless: bool = False):
    """Tworzy kolejkę zadań i uruchamia wątek-demon browsera."""
    q: '_queue.Queue' = _queue.Queue()
    t = threading.Thread(target=_browser_worker, args=(q, headless), daemon=True)
    t.start()
    return q


# Kolejki zadań — wątki startują przy pierwszym użyciu (lazy)
_scraper_queue: '_queue.Queue | None' = None
_scraper_queue_lock = threading.Lock()

_fnac_queue: '_queue.Queue | None' = None
_fnac_queue_lock = threading.Lock()


def _get_scraper_queue() -> '_queue.Queue':
    global _scraper_queue
    if _scraper_queue is None:
        with _scraper_queue_lock:
            if _scraper_queue is None:
                _scraper_queue = _make_browser_worker(headless=False)
    return _scraper_queue


def _get_fnac_queue() -> '_queue.Queue':
    global _fnac_queue
    if _fnac_queue is None:
        with _fnac_queue_lock:
            if _fnac_queue is None:
                _fnac_queue = _make_browser_worker(headless=False)
    return _fnac_queue


def _dispatch_fetch(task_queue: '_queue.Queue', url: str, timeout: int = 45) -> str:
    """Wysyła zadanie do wątku-browsera i czeka na wynik."""
    result_q: '_queue.Queue' = _queue.Queue()
    task_queue.put((url, result_q))
    status, value = result_q.get(timeout=timeout)
    if status == 'err':
        raise value
    return value


def _fetch_with_browser(url: str) -> str:
    """Fetch page using the persistent off-screen browser (worker thread)."""
    return _dispatch_fetch(_get_scraper_queue(), url)


def _fetch_fnac(url: str) -> str:
    """Fetch fnacpro.com using a persistent browser (worker thread)."""
    return _dispatch_fetch(_get_fnac_queue(), url)


def scrape_product(url: str) -> dict:
    """
    Fetch product page and return:
        name, url, store, thumbnail_url, price, currency
    """
    store = detect_store(url)

    # Sprawdź czy sklep używa CSS-selector (dodany przez wizard)
    css_config = next(
        (cfg for domain, cfg in _css_store_configs.items() if domain in url),
        None,
    )

    # 1. fnacpro wymaga świeżego procesu Playwright (wykrywa trwały kontekst)
    if 'fnacpro.com' in url:
        html = _fetch_fnac(url)
    else:
        # 2. Fast path — curl_cffi
        html = _fetch_curl(url)
        # 3. Fallback — persistent off-screen browser
        if html is None or '<html><head></head><body></body></html>' in html:
            html = _fetch_with_browser(url)

    if css_config:
        return _extract_css(html, url, store, css_config)

    data = _parse_json_ld(html)
    return _extract_product(data, url, store)


def _extract_css(html: str, url: str, store: str, config: dict) -> dict:
    """Ekstrakcja danych produktu przy użyciu CSS-selektorów z konfiguracji."""
    soup = BeautifulSoup(html, 'lxml')
    selectors = config.get('selectors', {})

    def _text(sel):
        if not sel:
            return None
        el = soup.select_one(sel)
        return el.get_text(strip=True) if el else None

    name  = _text(selectors.get('name'))  or 'Nieznany produkt'
    brand = _text(selectors.get('brand')) or ''

    raw_price = _text(selectors.get('price')) or ''
    price = _parse_css_price(raw_price, config.get('price_type'), config.get('vat_rate', 20))

    # Thumbnail: use wizard-selected selector if set, else fall back to og:image
    thumb_sel = selectors.get('thumbnail', '')
    if thumb_sel:
        img_el = soup.select_one(thumb_sel)
        thumbnail_url = (
            img_el.get('src') or img_el.get('data-src') or img_el.get('data-lazy-src')
            if img_el else None
        )
    else:
        og_img = soup.find('meta', property='og:image')
        thumbnail_url = og_img['content'] if og_img and og_img.get('content') else None

    return {
        'name':          name,
        'url':           url,
        'store':         store,
        'thumbnail_url': thumbnail_url,
        'price':         price,
        'currency':      config.get('currency', 'EUR'),
        'brand':         brand,
    }


def _parse_css_price(raw: str, price_type: str, vat_rate: int) -> float | None:
    """Wyciąga float z tekstu ceny; obsługuje '1 234,56 €' i '1234.56'."""
    m = re.search(r'[\d\s\u00a0\u202f]+[,.]?\d*', raw)
    if not m:
        return None
    s = m.group().replace(' ', '').replace('\u00a0', '').replace('\u202f', '')
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
