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
        ''')
        _migrate(conn)


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


def add_product(name, url, store, thumbnail_url, price, currency):
    with get_db() as conn:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute('''
            INSERT INTO products (name, url, store, thumbnail_url, current_price, min_price, currency, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, url, store, thumbnail_url, price, price, currency, now))
        product_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.execute(
            'INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)',
            (product_id, price, now)
        )
    return product_id


def update_price(product_id, new_price):
    with get_db() as conn:
        product = conn.execute(
            'SELECT * FROM products WHERE id = ?', (product_id,)
        ).fetchone()
        if not product:
            return False
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_min = min(product['min_price'] or new_price, new_price)
        conn.execute('''
            UPDATE products
            SET previous_price = current_price,
                current_price  = ?,
                min_price      = ?,
                last_updated   = ?
            WHERE id = ?
        ''', (new_price, new_min, now, product_id))
        conn.execute(
            'INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)',
            (product_id, new_price, now)
        )
    return True


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


def update_thumbnail(product_id, local_path):
    with get_db() as conn:
        conn.execute('UPDATE products SET thumbnail_url = ? WHERE id = ?',
                     (local_path, product_id))


def delete_product(product_id):
    with get_db() as conn:
        conn.execute('DELETE FROM products WHERE id = ?', (product_id,))


def get_price_history(product_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT price, checked_at FROM price_history WHERE product_id = ? ORDER BY checked_at ASC',
            (product_id,)
        ).fetchall()
