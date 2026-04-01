import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'prices.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn):
    """Add columns introduced after initial release."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(products)")}
    if 'is_dropship' not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN is_dropship INTEGER DEFAULT 0")
    if 'sale_price' not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN sale_price REAL")
    if 'brand' not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN brand TEXT DEFAULT ''")
    if 'is_favorite' not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN is_favorite INTEGER DEFAULT 0")
    if 'price_changed_at' not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN price_changed_at TEXT")


def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                store TEXT NOT NULL,
                thumbnail_url TEXT,
                current_price REAL,
                previous_price REAL,
                min_price REAL,
                currency TEXT DEFAULT 'EUR',
                is_dropship INTEGER DEFAULT 0,
                last_updated TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                price REAL NOT NULL,
                checked_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                product_id INTEGER,
                product_name TEXT,
                product_store TEXT,
                run_id TEXT,
                details TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        ''')
        _migrate(conn)


def log_event(event_type: str, product_id=None, product_name=None,
              product_store=None, run_id=None, details: dict = None):
    with get_db() as conn:
        conn.execute(
            '''INSERT INTO event_log
               (event_type, product_id, product_name, product_store, run_id, details)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (event_type, product_id, product_name, product_store,
             run_id, json.dumps(details or {}))
        )


def get_event_log(limit: int = 1000) -> list:
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM event_log ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()


def get_all_products():
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM products ORDER BY created_at DESC'
        ).fetchall()


def get_product(product_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM products WHERE id = ?', (product_id,)
        ).fetchone()


def add_product(name, url, store, thumbnail_url, price, currency, brand=''):
    with get_db() as conn:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute('''
            INSERT INTO products (name, url, store, thumbnail_url, current_price, min_price, currency, brand, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, url, store, thumbnail_url, price, price, currency, brand, now))
        product_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.execute(
            'INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)',
            (product_id, price, now)
        )
    return product_id


def update_price(product_id, new_price, brand=None):
    """Update product price. new_price=None means product is unavailable (keeps old price)."""
    with get_db() as conn:
        product = conn.execute(
            'SELECT * FROM products WHERE id = ?', (product_id,)
        ).fetchone()
        if not product:
            return False
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if new_price is None:
            # Unavailable — update timestamp only (preserve current price)
            if brand is not None:
                conn.execute(
                    'UPDATE products SET last_updated = ?, brand = ? WHERE id = ?',
                    (now, brand, product_id)
                )
            else:
                conn.execute(
                    'UPDATE products SET last_updated = ? WHERE id = ?',
                    (now, product_id)
                )
        else:
            new_min = min(product['min_price'] or new_price, new_price)
            price_changed = (product['current_price'] is not None and
                             product['current_price'] != new_price)
            changed_at = now if price_changed else product['price_changed_at']
            if brand is not None:
                conn.execute('''
                    UPDATE products
                    SET previous_price  = current_price,
                        current_price   = ?,
                        min_price       = ?,
                        last_updated    = ?,
                        brand           = ?,
                        price_changed_at = ?
                    WHERE id = ?
                ''', (new_price, new_min, now, brand, changed_at, product_id))
            else:
                conn.execute('''
                    UPDATE products
                    SET previous_price  = current_price,
                        current_price   = ?,
                        min_price       = ?,
                        last_updated    = ?,
                        price_changed_at = ?
                    WHERE id = ?
                ''', (new_price, new_min, now, changed_at, product_id))
            conn.execute(
                'INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)',
                (product_id, new_price, now)
            )
    return True


def toggle_favorite(product_id):
    with get_db() as conn:
        conn.execute(
            'UPDATE products SET is_favorite = 1 - is_favorite WHERE id = ?',
            (product_id,)
        )
        row = conn.execute(
            'SELECT is_favorite FROM products WHERE id = ?', (product_id,)
        ).fetchone()
    return bool(row['is_favorite']) if row else False


def toggle_dropship(product_id):
    with get_db() as conn:
        conn.execute(
            'UPDATE products SET is_dropship = 1 - is_dropship WHERE id = ?',
            (product_id,)
        )
        row = conn.execute(
            'SELECT is_dropship FROM products WHERE id = ?', (product_id,)
        ).fetchone()
    return bool(row['is_dropship']) if row else False


def update_brand_only(product_id, brand):
    with get_db() as conn:
        conn.execute('UPDATE products SET brand = ? WHERE id = ?', (brand, product_id))


def update_thumbnail(product_id, local_path):
    with get_db() as conn:
        conn.execute('UPDATE products SET thumbnail_url = ? WHERE id = ?',
                     (local_path, product_id))


def update_sale_price(product_id, sale_price):
    with get_db() as conn:
        conn.execute('UPDATE products SET sale_price = ? WHERE id = ?',
                     (sale_price, product_id))


def update_min_price(product_id, min_price):
    with get_db() as conn:
        conn.execute('UPDATE products SET min_price = ? WHERE id = ?',
                     (min_price, product_id))


def delete_product(product_id):
    with get_db() as conn:
        conn.execute('DELETE FROM products WHERE id = ?', (product_id,))


def get_price_history(product_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT price, checked_at FROM price_history WHERE product_id = ? ORDER BY checked_at ASC',
            (product_id,)
        ).fetchall()
