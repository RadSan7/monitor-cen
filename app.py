import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests as req_lib
import database as db
import scraper

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

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'GET':
        return render_template('add_product.html')

    action = request.form.get('action')

    if action == 'preview':
        url = request.form.get('url', '').strip()
        if not url:
            flash('Podaj URL produktu.', 'warning')
            return render_template('add_product.html')
        try:
            data = scraper.scrape_product(url)
            return render_template('add_product.html', preview=data)
        except Exception as e:
            flash(f'Błąd pobierania produktu: {e}', 'danger')
            return render_template('add_product.html', prefill_url=url)

    if action == 'confirm':
        try:
            product_id = db.add_product(
                name=request.form['name'],
                url=request.form['url'],
                store=request.form['store'],
                thumbnail_url=request.form.get('thumbnail_url') or None,
                price=float(request.form['price']),
                currency=request.form['currency'],
            )
            _save_thumbnail(product_id, request.form.get('thumbnail_url'))
            flash('Produkt dodany pomyślnie!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Błąd zapisu: {e}', 'danger')
            return render_template('add_product.html')

    return render_template('add_product.html')


# ── Bulk add products ─────────────────────────────────────────────────────────

@app.route('/add/bulk', methods=['POST'])
def add_bulk():
    raw = request.form.get('urls', '')
    urls = [u.strip() for u in raw.splitlines() if u.strip()]
    if not urls:
        flash('Wklej co najmniej jeden URL.', 'warning')
        return render_template('add_product.html', active_tab='bulk', prefill_urls=raw)

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
    try:
        data = scraper.scrape_product(product['url'])
        db.update_price(product_id, data['price'])
        return jsonify({
            'success': True,
            'price': data['price'],
            'currency': data['currency'],
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
            db.update_price(p['id'], data['price'])
            results.append({'id': p['id'], 'success': True, 'price': data['price']})
        except Exception as e:
            results.append({'id': p['id'], 'success': False, 'error': str(e)})
    return jsonify(results)


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
