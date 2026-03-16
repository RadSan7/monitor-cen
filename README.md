# Monitor Cen 📊

Aplikacja do monitorowania cen produktów z francuskich sklepów internetowych — **fnacpro.com** i **homecinesolutions.fr**.

## Funkcje

✅ **Dodawanie produktów** — wklejenie URL lub bulk import (wiele linków na raz)
✅ **Śledzenie cen** — historyczne dane cen dla każdego produktu
✅ **Wyszukiwanie** — szybkie filtrowanie listy produktów
✅ **Filtry** — dropship, zmiana ceny, aktywne produkty
✅ **Miniaturki** — pobieranie i przechowywanie offline
✅ **Automatyzacja** — scheduler do uruchamiania aktualizacji w Claude Code

---

## Instalacja

### 1. Klonowanie i setup
```bash
git clone <repo-url>
cd "Monitor cen"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Uruchomienie
```bash
python app.py
```

Aplikacja będzie dostępna pod: **http://localhost:5000**

---

## Użytkowanie

### Dodawanie produktów

#### Jeden produkt
1. Przejdź na `/add` → zakładka "Jeden produkt"
2. Wklej URL produktu
3. Kliknij "Pobierz informacje o produkcie"
4. Zatwierdź dane i dodaj

#### Wiele produktów (bulk)
1. Przejdź na `/add` → zakładka "Bulk (wiele linków)"
2. Wklej linki (jeden na linię)
3. Kliknij "Pobierz i dodaj wszystkie"
4. Sprawdź wyniki importu

### Aktualizacja cen

- **Ręczna** — przycisk "Aktualizuj" przy każdym produkcie lub "Aktualizuj wszystkie"
- **Automatyczna** — scheduler w Claude Code (procedura `start-monitor-cen`)

### Filtry i wyszukiwanie

- **Wyszukiwanie tekstowe** — szuka po nazwie i sklepie
- **Filtr Dropship** — wyświetla tylko produkty oznaczone jako dropship
- **Filtr zmiana ceny** — tylko produkty z różnicą względem ostatniego okresu

---

## Struktura projektu

```
Monitor cen/
├── app.py                  # Flask routes
├── database.py             # Operacje SQLite
├── scraper.py              # Web scraping
├── requirements.txt        # Zależności
├── templates/              # HTML (Jinja2)
├── static/
│   ├── css/
│   ├── js/
│   └── thumbs/            # Pobrane miniaturki
├── prices.db              # Baza danych (auto-tworzony)
└── .claude/launch.json    # Konfiguracja preview_start
```

---

## Technologia

- **Backend**: Flask (Python)
- **Baza**: SQLite
- **Scraping**: requests + BeautifulSoup4, Playwright (dla JS-heavy stron)
- **Frontend**: Bootstrap 5 + Vanilla JS
- **Anti-bot**: User-Agent headers, opóźnienia między requestami, JSON-LD parsing

---

## Automatyzacja w Claude Code

Scheduled task **`start-monitor-cen`** uruchamia serwer na żądanie:

1. Otwórz Claude Code
2. Przejdź do **Scheduled** w panelu bocznym
3. Znajdź `start-monitor-cen` → kliknij **Run**

Lub po prostu napisz: *"uruchom monitor cen"*

---

## Ograniczenia i known issues

⚠️ **Anti-bot protection** — fnacpro.com i homecinesolutions.fr mają ochronę Cloudflare i mogą blokować IP po intensywnym scrapingu
⚠️ **ToS** — homecinesolutions.fr jawnie zabrania automatycznego scrapingu w robots.txt
⚠️ **JavaScript** — niektóre strony ładują ceny dynamicznie (wymaga Playwright)

---

## Licencja

MIT — wolno używać do celów edukacyjnych i prywatnych.

---

## Support

Pytania? Sprawdź konsole Flask (`app.py` logs) i przeglądarki (DevTools) aby zdiagnozować błędy scrapingu.
