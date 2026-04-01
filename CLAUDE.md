# Monitor Cen — instrukcje dla Claude

## Uruchomienie

```bash
# Przez skrypt (zalecane):
./monitor_cen           # start z auto-shutdown
./monitor_cen no-auto   # start bez auto-shutdown
./monitor_cen stop      # zatrzymaj serwer

# Bezpośrednio:
cd "/Users/a12345678/Pliki/Claude/Monitor cen"
PORT=5001 .venv/bin/python app.py
# Port 5000 zajmuje macOS AirPlay — używaj 5001
```

## Stack

- **Backend**: Flask + SQLite (`prices.db`) + BeautifulSoup
- **Scraping**: curl_cffi (szybkie, bez okna) → fallback Playwright headless=False
- **Frontend**: Bootstrap 5 + vanilla JS, Jinja2 templates

## Pliki kluczowe

| Plik | Rola |
|------|------|
| `app.py` | Endpointy Flask |
| `scraper.py` | Pobieranie cen z URL |
| `database.py` | SQLite CRUD |
| `wizard.py` | Sesje integracji (Playwright) |
| `static/wizard_overlay.js` | JS wstrzykiwany do sklepu przez wizard |
| `stores.json` | Konfiguracje sklepów dodanych przez wizard |
| `templates/` | HTML (base, index, product, add_product, integrations, wizard) |

## Obsługiwane sklepy

### Hardcoded (JSON-LD schema.org)
- `fnacpro.com` — wymaga Playwright headless=**False** (wykrywa headless)
- `homecinesolutions.fr` — curl_cffi, ceny brutto TTC ÷ 1.20

### Dynamiczne (wizard integracji, CSS-selektory)
- Konfiguracja w `stores.json`, ładowana przez `scraper.reload_stores()`
- Scraping: curl_cffi → fallback Playwright

## Ważne obejścia

- **fnacpro.com**: pomija próbę headless, idzie od razu do `_playwright_once(url, headless=False)`
- **Playwright okno minimalizowane**: używa CDP `Browser.setWindowBounds` → `minimized`
- **CORS overlay JS → Flask**: `@app.after_request` ustawia `Access-Control-Allow-Origin: *`

## Schemat bazy danych (`prices.db`)

```sql
products (id, name, url, store, thumbnail_url, current_price, previous_price,
          min_price, currency, is_dropship, is_favorite, brand, sale_price,
          last_updated, created_at)

price_history (id, product_id, price, checked_at)
```

**Ważne**: `update_price()` aktualizuje **tylko cenę** — nie zmienia `name` ani `brand`.
Nazwa i marka pobierane są **wyłącznie przy dodawaniu** (`add_product`).

## Wizard integracji — przepływ

1. Otwierasz `/integrations` → "Nowy sklep" → Flask uruchamia Playwright
2. Overlay JS wstrzykiwany do strony sklepu
3. Użytkownik klika **Wybierz** przy polu (nazwa/marka/cena) → tryb zaznaczania
4. Klika element na stronie → selektor zapisany, wychodzi z trybu
5. Kliknięcie **Gotowe** w overlay → `/integrations/complete/<session_id>` → `step='complete'`
6. `wizard.html` widzi `step='complete'` (polling 1s) → pokazuje panel konfiguracji
7. Użytkownik ustawia typ ceny, VAT, walutę, nazwę sklepu → Test → Zapis

**Pola**:
- `name` — wymagane
- `brand` — opcjonalne (przycisk "Pomiń" → pusty selektor, `test_scrape` go omija)
- `price` — wymagane

## Funkcja Grok

Przycisk "Grok" w topbarze (`index.html`):
- Otwiera `https://grok.com/` w nowej karcie
- Pokazuje modal z promptem do skopiowania: szukaj okazji audio/hifi w EU sklepach do odsprzedaży w PL

## Konwencje kodu

- Komentarze sekcji: `# ── Tytuł ──────────...`
- Async Playwright tylko w `wizard.py` (sync_playwright); scraper używa sync
- AJAX endpointy zwracają `jsonify({'ok': True/False, ...})`
- Błędy scrapera: exception → Flask zwraca `jsonify({'error': ...}), 500`

## Changelog sesji

### 2026-04-01 (2)
- **Historia**: nowa strona `/history` — event_log w DB, logowanie we wszystkich endpointach (dodanie, usunięcie, zmiana ceny, błędy, edycja pól); runy grupowane przez `X-Run-Id` header z JS; filtry po typie/tekście/dacie
- **Navbar**: 4 zakładki (Home/Historia/Integracje/Dodaj produkt) + globalny przycisk Aktualizuj + mały dark toggle; Aktualizuj poza home → redirect `/?update=1`
- **Karta produktu**: sekcja 24h zmiany ceny z poprzednią → nową ceną i % (widoczna przez 24h od `price_changed_at`)
- **scraper.py**: pozycja okna zmieniona na dolny prawy róg (`9999,9999`); `_fix_focus_after_launch` łączy hide + activate w jednym `osascript` (delay 0.8 + `name contains "Chromium"`)
- **index.html JS**: wyodrębniony do `static/index_page.js`; `updateAll()` wysyła `X-Run-Id` header

### 2026-04-01
- **Focus fix**: Przerobiono `_restore_focus` → `_get_frontmost_app()` + `_restore_focus_to(app)` + `_hide_chromium()`; wywołanie po launchu przeglądarki (nie przed); AppleScript ukrywa proces Chromium żeby nie kradł focusu
- **Wielowątkowość**: `update_all` używa `ThreadPoolExecutor` z per-store semaforami (jeden produkt ze sklepu naraz, różne sklepy równolegle); JS `updateAll()` przerobiony na concurrent per-store przez `Promise.all`
- **Badge 24h**: `price_changed_at` w DB; badge "Nowa cena" pokazywany przez 24h po zmianie ceny
- **Heartbeat + watchdog**: JS co 10s wysyła `POST /heartbeat`; serwer wyłącza się po 35s bez heartbeatu (gdy karta zamknięta); `AUTO_SHUTDOWN=0` wyłącza tę funkcję
- **Skrypt uruchamiający**: plik `monitor_cen` (bash) z komendami `start`, `stop`, `no-auto`; endpoint `POST /admin/shutdown`

### 2026-03-28
- **Fix**: Playwright sync API błąd "cannot switch to a different thread (which happens to have exited)" — zmieniono architekturę na dedykowane wątki-demony (`_browser_worker`) z kolejkami zadań (`_queue.Queue`); każdy browser (fnacpro, scraper) ma własny długożyjący wątek, Flask-threads tylko wysyłają zadania i czekają na wynik

### 2026-03-27 (3)
- **Perf**: fnacpro.com używa teraz trwałego browsera zamiast nowego procesu przy każdym scrapie; świeży context per żądanie

### 2026-03-27 (2)
- **UI**: Przeniesiono przycisk "Aktualizuj" do navbara (przez `{% block navbar_extra %}` w `base.html`)
- **UI**: Przeprojektowano topbar filtrów: pogrupowane przyciski statusu (btn-group), rozdzielniki, uproszczony zakres cenowy
- **Integracje**: Dodano edycję konfiguracji sklepu (przycisk ✏️ + modal) — endpoint `POST /integrations/edit/<domain>` w `app.py`

### 2026-03-27
- **Fix**: delete nie działał — Bootstrap zamykał dropdown po 1. kliku, 2. klik był niemożliwy; zmieniono na `confirm()` dialog
- **Persistent browser**: `scraper.py` trzyma jeden trwały process Playwright (`_scraper_pw`, `_scraper_browser`) zamiast otwierać nowy przy każdym scrapie; okno nie wchodzi w focus po pierwszym uruchomieniu
- **macOS focus restore**: przy pierwszym uruchomieniu browser przywraca focus poprzedniej aplikacji przez `osascript`
- **Wizard thumbnail**: dodano pole `thumbnail` (opcjonalne, przycisk Pomiń) do overlay JS, `wizard.py` i `wizard.html`; `_extract_css` używa selektora thumbnail jeśli dostępny, wpp. fallback og:image

### 2026-03-26
- Dodano przycisk Grok w topbarze z promptem audio/hifi
- **Fix**: `test_scrape` pomija pola z pustym selektorem (crash gdy marka pominięta)
- **Fix**: Wizard overlay przeprojektowany — ręczny tryb zaznaczania (przycisk Wybierz/Anuluj/Gotowe), brak auto-advance między polami
- **Fix**: `update_product` i `update_all` nie nadpisują `brand` przy aktualizacji ceny
- **Fix**: `scraper.py` pomija headless dla fnacpro.com (szybszy fetch)
- Dodano endpoint `POST /integrations/complete/<session_id>`

## Instrukcje dla następnych sesji

1. **Zmiany opisuj w Changelog** — dodawaj datę i bullet points na górze sekcji
2. **Przed edycją wzorca scrapingu** sprawdź czy oba sklepy nadal zwracają JSON-LD:
   `curl -A "Mozilla/5.0" <url> | grep 'application/ld+json'`
3. **Nowe pole w DB** → dodaj do `_migrate()` w `database.py`
4. **Nowy endpoint** → trzymaj styl `# ── Nazwa ────...` przed dekoratorem `@app.route`
5. **Tryb serwera**: zawsze `PORT=5001` (5000 zajęty przez AirPlay)
6. **Przed push** sprawdź czy `stores.json` nie ma danych testowych do usunięcia
