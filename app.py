import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests as req_lib
import database as db
import scraper
import wizard

app = Flask(__name__)
app.secret_key = 'price-monitor-2026'

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
            product_id = db.add_product(
                name=request.form['name'],
                url=request.form['url'],
                store=request.form['store'],
                thumbnail_url=request.form.get('thumbnail_url') or None,
                price=float(request.form['price']),
                currency=request.form['currency'],
                brand=request.form.get('brand', ''),
            )
            _save_thumbnail(product_id, request.form.get('thumbnail_url'))
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
    try:
        data = scraper.scrape_product(product['url'])
        new_price = data['price']
        db.update_price(product_id, new_price, brand=data.get('brand') or None)
        price_changed = (
            old_price is not None and new_price is not None and old_price != new_price
        )
        return jsonify({
            'success': True,
            'price': new_price,
            'currency': data['currency'],
            'old_price': old_price,
            'price_changed': price_changed,
            'unavailable': new_price is None,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Update all products (AJAX) ────────────────────────────────────────────────

@app.route('/update-all', methods=['POST'])
def update_all():
    products = db.get_all_products()
    results = []
    for p in products:
        try:
            data = scraper.scrape_product(p['url'])
            db.update_price(p['id'], data['price'], brand=data.get('brand') or None)
            results.append({'id': p['id'], 'success': True, 'price': data['price']})
        except Exception as e:
            results.append({'id': p['id'], 'success': False, 'error': str(e)})
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
    thumb = os.path.join(THUMBS_DIR, f'{product_id}.jpg')
    if os.path.exists(thumb):
        os.remove(thumb)
    db.delete_product(product_id)
    return jsonify({'success': True})


# ── Set brand (AJAX) ─────────────────────────────────────────────────────────

@app.route('/brand/<int:product_id>', methods=['POST'])
def set_brand(product_id):
    brand = request.form.get('brand', '').strip()
    db.update_brand_only(product_id, brand)
    return jsonify({'success': True, 'brand': brand})


# ── Set sale price ────────────────────────────────────────────────────────────

@app.route('/sale-price/<int:product_id>', methods=['POST'])
def set_sale_price(product_id):
    val = request.form.get('sale_price', '').strip()
    price = float(val) if val else None
    db.update_sale_price(product_id, price)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'sale_price': price})
    return redirect(url_for('product_detail', product_id=product_id))


# ── Set min price (AJAX) ─────────────────────────────────────────────────────

@app.route('/min-price/<int:product_id>', methods=['POST'])
def set_min_price(product_id):
    val = request.form.get('min_price', '').strip()
    price = float(val) if val else None
    db.update_min_price(product_id, price)
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


# ── Integrations wizard ───────────────────────────────────────────────────────

@app.route('/integrations')
def integrations():
    css_stores = list(scraper._css_store_configs.values())
    return render_template(
        'integrations.html',
        json_ld_stores=scraper.SUPPORTED_STORES,
        css_stores=css_stores,
    )


@app.route('/integrations/start', methods=['POST'])
def integrations_start():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'Podaj URL produktu'}), 400

    # Sprawdź czy domena nie jest już skonfigurowana
    from urllib.parse import urlparse
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


@app.route('/wizard/<session_id>')
def wizard_page(session_id):
    status = wizard.get_status(session_id)
    if 'error' in status:
        flash('Sesja wizarda nie istnieje lub wygasła.', 'warning')
        return redirect(url_for('integrations'))
    return render_template('wizard.html', session_id=session_id, domain=status['domain'])


@app.route('/integrations/delete/<domain>', methods=['POST'])
def integrations_delete(domain):
    from pathlib import Path
    import json as _json
    p = Path(__file__).parent / 'stores.json'
    if p.exists():
        data = _json.loads(p.read_text(encoding='utf-8'))
        data['stores'] = [s for s in data['stores'] if s['domain'] != domain]
        p.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    scraper.reload_stores()
    return jsonify({'ok': True})


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
    print("Monitor Cen uruchomiony: http://localhost:5000")
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)
