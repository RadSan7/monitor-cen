import json
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests as req_lib
import database as db
import scraper
import wizard

app = Flask(__name__)
app.secret_key = 'price-monitor-2026'

def _update_one_product(p) -> dict:
    """Aktualizuje jeden produkt (używane przez /update-all)."""
    try:
        data = scraper.scrape_product(p['url'])
        db.update_price(p['id'], data['price'])
        return {'id': p['id'], 'success': True, 'price': data['price']}
    except Exception as e:
        return {'id': p['id'], 'success': False, 'error': str(e)}


# ── Heartbeat / auto-shutdown ─────────────────────────────────────────────────
_last_heartbeat: float | None = None
_HEARTBEAT_TIMEOUT = 35  # sekund; po tym czasie bez heartbeatu serwer się wyłącza


def _watchdog():
    """Wątek-demon: wyłącza serwer gdy karta przeglądarki zostanie zamknięta."""
    while True:
        time.sleep(5)
        if _last_heartbeat is not None and time.time() - _last_heartbeat > _HEARTBEAT_TIMEOUT:
            print('\n[monitor_cen] Brak heartbeatu — zamykam serwer.')
            os.kill(os.getpid(), signal.SIGTERM)


@app.after_request
def _cors(response):
    """Zezwól na cross-origin fetch z wstrzykniętego overlay JS (Chromium → localhost)."""
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/integrations/capture/<session_id>', methods=['OPTIONS'])
@app.route('/integrations/ping', methods=['OPTIONS'])
def _cors_preflight(**kwargs):
    """Obsługa CORS preflight dla endpointów wywoływanych przez overlay JS."""
    return app.make_response(('', 204))

THUMBS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'thumbs')
os.makedirs(THUMBS_DIR, exist_ok=True)


def _save_thumbnail(product_id, remote_url):
    """Download thumbnail and store locally; silently skips on error."""
    if not remote_url:
        return
    try:
        resp = req_lib.get(remote_url, timeout=10,
                           headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code == 200:
            local_path = os.path.join(THUMBS_DIR, f'{product_id}.jpg')
            with open(local_path, 'wb') as f:
                f.write(resp.content)
            db.update_thumbnail(product_id, f'/static/thumbs/{product_id}.jpg')
    except Exception:
        pass


def _get_grok_prompt():
    """Get the prompt for Grok search."""
    return (
        "Szukaj promocji i okazji na sprzęt audio/hi-fi w europejskich sklepach internetowych. "
        "Skoncentruj się na produktach, które mogę kupić taniej w krajach takich jak Niemcy, Francja, Holandia czy Austria, "
        "a następnie odsprzedać z zyskiem w Polsce. Podaj konkretne produkty, sklepy, ceny i linki."
    )


# ── Main list ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    products = db.get_all_products()
    return render_template('index.html', products=products)


# ── Add product ───────────────────────────────────────────────────────────────

def _all_store_domains():
    """Zwraca listę wszystkich obsługiwanych domen (JSON-LD + CSS-selector)."""
    return list(scraper.SUPPORTED_STORES.keys()) + list(scraper._css_store_configs.keys())


@app.route('/add', methods=['GET', 'POST'])
def add_product():
    stores = _all_store_domains()
    if request.method == 'GET':
        return render_template('add_product.html', supported_stores=stores)

    action = request.form.get('action')

    if action == 'preview':
        url = request.form.get('url', '').strip()
        if not url:
            flash('Podaj URL produktu.', 'warning')
            return render_template('add_product.html', supported_stores=stores)
        try:
            data = scraper.scrape_product(url)
            return render_template('add_product.html', preview=data, supported_stores=stores)
        except Exception as e:
            flash(f'Błąd pobierania produktu: {e}', 'danger')
            return render_template('add_product.html', prefill_url=url, supported_stores=stores)

    if action == 'confirm':
        try:
            price = float(request.form['price'])
            product_id = db.add_product(
                name=request.form['name'],
                url=request.form['url'],
                store=request.form['store'],
                thumbnail_url=request.form.get('thumbnail_url') or None,
                price=price,
                currency=request.form['currency'],
                brand=request.form.get('brand', ''),
            )
            _save_thumbnail(product_id, request.form.get('thumbnail_url'))
            db.log_event('product_added', product_id=product_id,
                         product_name=request.form['name'],
                         product_store=request.form['store'],
                         details={'price': price, 'currency': request.form['currency']})
            flash('Produkt dodany pomyślnie!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Błąd zapisu: {e}', 'danger')
            return render_template('add_product.html', supported_stores=stores)

    return render_template('add_product.html', supported_stores=stores)


# ── Bulk add products ─────────────────────────────────────────────────────────

@app.route('/add/bulk', methods=['POST'])
def add_bulk():
    stores = _all_store_domains()
    raw = request.form.get('urls', '')
    urls = [u.strip() for u in raw.splitlines() if u.strip()]
    if not urls:
        flash('Wklej co najmniej jeden URL.', 'warning')
        return render_template('add_product.html', active_tab='bulk', prefill_urls=raw, supported_stores=stores)

    results = []
    for url in urls:
        try:
            data = scraper.scrape_product(url)
            product_id = db.add_product(
                name=data['name'],
                url=data['url'],
                store=data['store'],
                thumbnail_url=data['thumbnail_url'],
                price=data['price'],
                currency=data['currency'],
                brand=data.get('brand', ''),
            )
            _save_thumbnail(product_id, data['thumbnail_url'])
            results.append({'url': url, 'success': True, 'data': data})
        except Exception as e:
            results.append({'url': url, 'success': False, 'error': str(e)})

    added  = sum(1 for r in results if r['success'])
    failed = len(results) - added
    return render_template('bulk_result.html', results=results, added=added, failed=failed)


# ── Update single product (AJAX) ──────────────────────────────────────────────

@app.route('/update/<int:product_id>', methods=['POST'])
def update_product(product_id):
    product = db.get_product(product_id)
    if not product:
        return jsonify({'error': 'Produkt nie istnieje'}), 404
    old_price = product['current_price']
    run_id = request.headers.get('X-Run-Id')
    try:
        data = scraper.scrape_product(product['url'])
        new_price = data['price']
        db.update_price(product_id, new_price)
        price_changed = (
            old_price is not None and new_price is not None and old_price != new_price
        )
        if price_changed:
            pct = round((new_price - old_price) / old_price * 100, 2) if old_price else 0
            db.log_event('price_changed', product_id=product_id,
                         product_name=product['name'], product_store=product['store'],
                         run_id=run_id,
                         details={'old_price': old_price, 'new_price': new_price,
                                  'currency': data['currency'], 'pct': pct})
        elif new_price is None and old_price is not None:
            db.log_event('price_unavailable', product_id=product_id,
                         product_name=product['name'], product_store=product['store'],
                         run_id=run_id, details={})
        return jsonify({
            'success': True,
            'price': new_price,
            'currency': data['currency'],
            'old_price': old_price,
            'price_changed': price_changed,
            'unavailable': new_price is None,
        })
    except Exception as e:
        db.log_event('scrape_error', product_id=product_id,
                     product_name=product['name'], product_store=product['store'],
                     run_id=run_id, details={'error': str(e)})
        return jsonify({'error': str(e)}), 500


# ── Update all products — równolegle, jeden produkt ze sklepu naraz ──────────

@app.route('/update-all', methods=['POST'])
def update_all():
    products = db.get_all_products()
    if not products:
        return jsonify([])
    # Liczba workerów: jeden per sklep, ale max 8
    n_stores = len({p['store'] for p in products})
    workers  = min(n_stores, 8)
    results  = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_update_one_product, p): p for p in products}
        for f in as_completed(futures):
            results.append(f.result())
    return jsonify(results)


# ── Toggle favorite (AJAX) ───────────────────────────────────────────────────

@app.route('/favorite/<int:product_id>', methods=['POST'])
def toggle_favorite(product_id):
    new_state = db.toggle_favorite(product_id)
    return jsonify({'success': True, 'is_favorite': new_state})


# ── Toggle dropship (AJAX) ───────────────────────────────────────────────────

@app.route('/dropship/<int:product_id>', methods=['POST'])
def toggle_dropship(product_id):
    new_state = db.toggle_dropship(product_id)
    return jsonify({'success': True, 'is_dropship': new_state})


# ── Delete product (AJAX) ─────────────────────────────────────────────────────

@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = db.get_product(product_id)
    if product:
        db.log_event('product_deleted', product_id=product_id,
                     product_name=product['name'], product_store=product['store'],
                     details={'price': product['current_price'],
                              'currency': product['currency']})
    thumb = os.path.join(THUMBS_DIR, f'{product_id}.jpg')
    try:
        os.remove(thumb)
    except FileNotFoundError:
        pass
    db.delete_product(product_id)
    return jsonify({'success': True})


# ── Set brand (AJAX) ─────────────────────────────────────────────────────────

@app.route('/brand/<int:product_id>', methods=['POST'])
def set_brand(product_id):
    product = db.get_product(product_id)
    brand = request.form.get('brand', '').strip()
    db.update_brand_only(product_id, brand)
    if product:
        db.log_event('field_updated', product_id=product_id,
                     product_name=product['name'], product_store=product['store'],
                     details={'field': 'brand', 'old_value': product['brand'], 'new_value': brand})
    return jsonify({'success': True, 'brand': brand})


# ── Set sale price ────────────────────────────────────────────────────────────

@app.route('/sale-price/<int:product_id>', methods=['POST'])
def set_sale_price(product_id):
    product = db.get_product(product_id)
    val = request.form.get('sale_price', '').strip()
    price = float(val) if val else None
    db.update_sale_price(product_id, price)
    if product:
        db.log_event('field_updated', product_id=product_id,
                     product_name=product['name'], product_store=product['store'],
                     details={'field': 'sale_price',
                              'old_value': product['sale_price'], 'new_value': price})
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'sale_price': price})
    return redirect(url_for('product_detail', product_id=product_id))


# ── Set min price (AJAX) ─────────────────────────────────────────────────────

@app.route('/min-price/<int:product_id>', methods=['POST'])
def set_min_price(product_id):
    product = db.get_product(product_id)
    val = request.form.get('min_price', '').strip()
    price = float(val) if val else None
    db.update_min_price(product_id, price)
    if product:
        db.log_event('field_updated', product_id=product_id,
                     product_name=product['name'], product_store=product['store'],
                     details={'field': 'min_price',
                              'old_value': product['min_price'], 'new_value': price})
    return jsonify({'success': True, 'min_price': price})


# ── Product detail + price history ───────────────────────────────────────────

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = db.get_product(product_id)
    if not product:
        flash('Produkt nie istnieje.', 'warning')
        return redirect(url_for('index'))
    history = db.get_price_history(product_id)
    return render_template('product.html', product=product, history=history)


# ── Historia zdarzeń ─────────────────────────────────────────────────────────

@app.route('/history')
def history():
    raw = db.get_event_log(limit=2000)
    timeline = []
    seen_runs: set = set()
    run_buckets: dict = {}  # run_id -> list of events

    # First pass: build run buckets
    for ev in raw:
        if ev['run_id']:
            run_buckets.setdefault(ev['run_id'], []).append(ev)

    # Second pass: build timeline preserving order (newest first)
    for ev in raw:
        if ev['run_id']:
            rid = ev['run_id']
            if rid not in seen_runs:
                events = run_buckets[rid]
                n_changed = sum(1 for e in events if e['event_type'] == 'price_changed')
                n_errors  = sum(1 for e in events if e['event_type'] == 'scrape_error')
                n_unavail = sum(1 for e in events if e['event_type'] == 'price_unavailable')
                items = []
                for re in events:
                    items.append({**dict(re),
                                  'details_parsed': json.loads(re['details'] or '{}')})
                timeline.append({
                    'kind': 'run',
                    'run_id': rid,
                    'events': items,
                    'created_at': ev['created_at'],
                    'n_total': len(events),
                    'n_changed': n_changed,
                    'n_errors': n_errors,
                    'n_unavail': n_unavail,
                })
                seen_runs.add(rid)
        else:
            timeline.append({
                'kind': 'event',
                'data': {**dict(ev),
                         'details_parsed': json.loads(ev['details'] or '{}')},
            })

    return render_template('history.html', timeline=timeline)


# ── Integrations wizard ───────────────────────────────────────────────────────

@app.route('/integrations')
def integrations():
    css_stores = list(scraper._css_store_configs.values())
    return render_template(
        'integrations.html',
        json_ld_stores=scraper.SUPPORTED_STORES,
        css_stores=css_stores,
    )


@app.route('/integrations/ping', methods=['POST'])
def integrations_ping():
    """Warmup endpoint — wyzwala dialog uprawnień macOS przed pierwszym capture."""
    return jsonify({'ok': True})


@app.route('/integrations/start', methods=['POST'])
def integrations_start():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'Podaj URL produktu'}), 400

    # Sprawdź czy domena nie jest już skonfigurowana
    domain = urlparse(url).netloc.removeprefix('www.')
    if any(d in url for d in scraper.SUPPORTED_STORES) or domain in scraper._css_store_configs:
        return jsonify({'error': f'Sklep {domain} jest już skonfigurowany'}), 400

    try:
        host = request.host  # np. "localhost:5000"
        port = int(host.split(':')[-1]) if ':' in host else 5000
        session_id = wizard.start_session(url, flask_port=port)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'session_id': session_id, 'domain': domain})


@app.route('/integrations/status/<session_id>')
def integrations_status(session_id):
    status = wizard.get_status(session_id)
    if 'error' in status:
        return jsonify(status), 404
    return jsonify(status)


@app.route('/integrations/capture/<session_id>', methods=['POST'])
def integrations_capture(session_id):
    data = request.get_json(force=True)
    field   = data.get('field', '')
    selector = data.get('selector', '')
    preview  = data.get('preview', '')
    result = wizard.capture_field(session_id, field, selector, preview)
    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify(result)


@app.route('/integrations/test/<session_id>', methods=['POST'])
def integrations_test(session_id):
    data       = request.get_json(force=True)
    price_type = data.get('price_type', 'gross')
    vat_rate   = int(data.get('vat_rate', 20))
    currency   = data.get('currency', 'EUR')
    result = wizard.test_scrape(session_id, price_type, vat_rate, currency)
    return jsonify(result)


@app.route('/integrations/save/<session_id>', methods=['POST'])
def integrations_save(session_id):
    data         = request.get_json(force=True)
    display_name = data.get('display_name', '').strip()
    price_type   = data.get('price_type', 'gross')
    vat_rate     = int(data.get('vat_rate', 20))
    currency     = data.get('currency', 'EUR')
    if not display_name:
        return jsonify({'ok': False, 'error': 'Podaj nazwę sklepu'}), 400
    result = wizard.save_store(session_id, display_name, price_type, vat_rate, currency)
    return jsonify(result)


@app.route('/integrations/cancel/<session_id>', methods=['POST'])
def integrations_cancel(session_id):
    wizard.close_session(session_id)
    return jsonify({'ok': True})


@app.route('/integrations/complete/<session_id>', methods=['POST'])
def integrations_complete(session_id):
    result = wizard.complete_session(session_id)
    return jsonify(result)


@app.route('/wizard/<session_id>')
def wizard_page(session_id):
    status = wizard.get_status(session_id)
    if 'error' in status:
        flash('Sesja wizarda nie istnieje lub wygasła.', 'warning')
        return redirect(url_for('integrations'))
    return render_template('wizard.html', session_id=session_id, domain=status['domain'])


@app.route('/integrations/delete/<domain>', methods=['POST'])
def integrations_delete(domain):
    p = Path(__file__).parent / 'stores.json'
    if p.exists():
        data = json.loads(p.read_text(encoding='utf-8'))
        data['stores'] = [s for s in data['stores'] if s['domain'] != domain]
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    scraper.reload_stores()
    return jsonify({'ok': True})


# ── Edycja sklepu ──────────────────────────────────────────────────────────────

@app.route('/integrations/edit/<domain>', methods=['POST'])
def integrations_edit(domain):
    data_in      = request.get_json(force=True)
    display_name = data_in.get('display_name', '').strip()
    price_type   = data_in.get('price_type', 'gross')
    vat_rate     = int(data_in.get('vat_rate', 20))
    currency     = data_in.get('currency', 'EUR')
    if not display_name:
        return jsonify({'ok': False, 'error': 'Podaj nazwę sklepu'}), 400
    p = Path(__file__).parent / 'stores.json'
    if not p.exists():
        return jsonify({'ok': False, 'error': 'stores.json nie istnieje'}), 404
    stores_data = json.loads(p.read_text(encoding='utf-8'))
    updated = False
    for store in stores_data.get('stores', []):
        if store['domain'] == domain:
            store['display_name'] = display_name
            store['price_type']   = price_type
            store['vat_rate']     = vat_rate
            store['currency']     = currency
            updated = True
            break
    if not updated:
        return jsonify({'ok': False, 'error': f'Sklep {domain} nie istnieje'}), 404
    p.write_text(json.dumps(stores_data, ensure_ascii=False, indent=2), encoding='utf-8')
    scraper.reload_stores()
    return jsonify({'ok': True})


# ── Heartbeat (auto-shutdown gdy karta zamknięta) ─────────────────────────────

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    global _last_heartbeat
    _last_heartbeat = time.time()
    return jsonify({'ok': True})


# ── Admin: wyłącz serwer ──────────────────────────────────────────────────────

@app.route('/admin/shutdown', methods=['POST'])
def admin_shutdown():
    def _kill():
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_kill, daemon=True).start()
    return jsonify({'ok': True, 'message': 'Serwer zatrzymany.'})


# ── Grok audio search ─────────────────────────────────────────────────────────

@app.route('/grok-search', methods=['POST'])
def grok_search():
    """Return Grok search prompt and URL."""
    prompt = _get_grok_prompt()
    return jsonify({'prompt': prompt})


# ── Backfill brands (one-time admin route) ────────────────────────────────────

@app.route('/admin/backfill-brands', methods=['POST'])
def backfill_brands():
    products = db.get_all_products()
    results = []
    for p in products:
        if p['brand']:
            results.append({'id': p['id'], 'skipped': True})
            continue
        try:
            data = scraper.scrape_product(p['url'])
            if data.get('brand'):
                db.update_brand_only(p['id'], data['brand'])
            results.append({'id': p['id'], 'success': True, 'brand': data.get('brand', '')})
        except Exception as e:
            results.append({'id': p['id'], 'success': False, 'error': str(e)})
    return jsonify(results)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    db.init_db()
    # Backfill thumbnails for products that still have remote URLs
    for p in db.get_all_products():
        tid = p['thumbnail_url']
        if tid and tid.startswith('http'):
            _save_thumbnail(p['id'], tid)
    port = int(os.environ.get('PORT', 5001))
    # Watchdog — wyłącza serwer gdy karta przeglądarki zostanie zamknięta
    if os.environ.get('AUTO_SHUTDOWN', '1') != '0':
        threading.Thread(target=_watchdog, daemon=True).start()
    print(f'Monitor Cen uruchomiony: http://localhost:{port}')
    app.run(debug=True, port=port, threaded=True)
