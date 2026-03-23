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
import re
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


def _playwright_once(url: str, headless: bool) -> str:
    """Single Playwright fetch attempt."""
    pw = sync_playwright().start()
    try:
        args = ['--disable-blink-features=AutomationControlled']
        if not headless:
            # Move window far off-screen so it doesn't appear on the desktop
            args += ['--window-position=-10000,-10000', '--window-size=1280,800']
        browser = pw.chromium.launch(
            headless=headless,
            args=args,
        )
        context = browser.new_context(
            user_agent=_UA,
            locale='fr-FR',
            viewport={'width': 1280, 'height': 800},
        )
        context.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        )
        page = context.new_page()
        if not headless:
            # Minimalizuj okno przez CDP żeby nie zakłócać pracy
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
            browser.close()
            raise ConnectionError(
                "Strona nie załadowała się w czasie 30 s. Sprawdź połączenie."
            )
        html = page.content()
        browser.close()
    finally:
        pw.stop()
    return html


def _fetch_playwright(url: str) -> str:
    """Try headless first (no window); fall back to visible if bot-detected."""
    html = _playwright_once(url, headless=True)
    if 'application/ld+json' in html:
        return html
    # headless was detected — retry with visible browser
    return _playwright_once(url, headless=False)


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

    # 1. Fast path — curl_cffi
    html = _fetch_curl(url)

    # 2. Fallback — visible Playwright browser
    if html is None or '<html><head></head><body></body></html>' in html:
        if css_config:
            html = _fetch_playwright(url)
        else:
            html = _fetch_playwright(url)

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

    return {
        'name':          name,
        'url':           url,
        'store':         store,
        'thumbnail_url': None,
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
