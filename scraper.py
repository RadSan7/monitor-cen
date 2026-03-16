"""
Scraper for fnacpro.com and homecinesolutions.fr.

Strategy:
  1. Try curl_cffi (fast, no window) — works for homecinesolutions.fr
  2. If blocked (403/empty), fall back to Playwright headless=False
     — works for fnacpro.com which detects headless Chromium
"""

import json
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SUPPORTED_STORES = {
    'fnacpro.com': 'Fnac Pro',
    'homecinesolutions.fr': 'HomeCine Solutions',
}

_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)


def detect_store(url: str) -> str:
    for domain, name in SUPPORTED_STORES.items():
        if domain in url:
            return name
    raise ValueError(
        f"Nieobsługiwany sklep. Obsługiwane: {', '.join(SUPPORTED_STORES.keys())}"
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

    raw_price = offers.get('price')
    if raw_price is None:
        raise ValueError("Brak ceny w danych produktu")

    return {
        'name':          name,
        'url':           url,
        'store':         store,
        'thumbnail_url': thumbnail,
        'price':         float(raw_price),
        'currency':      offers.get('priceCurrency', 'EUR'),
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


def _fetch_playwright(url: str) -> str:
    """Return HTML via Playwright (headless=False bypasses bot detection)."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
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
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30_000)
            # Give JS a moment to inject any dynamic content
            page.wait_for_timeout(2_000)
        except PlaywrightTimeout:
            browser.close()
            raise ConnectionError(
                "Strona nie załadowała się w czasie 30 s. Sprawdź połączenie."
            )
        html = page.content()
        browser.close()
    return html


def scrape_product(url: str) -> dict:
    """
    Fetch product page and return:
        name, url, store, thumbnail_url, price, currency
    """
    store = detect_store(url)

    # 1. Fast path — curl_cffi
    html = _fetch_curl(url)

    # 2. Fallback — visible Playwright browser
    if html is None or '<html><head></head><body></body></html>' in html:
        html = _fetch_playwright(url)

    data = _parse_json_ld(html)
    return _extract_product(data, url, store)
