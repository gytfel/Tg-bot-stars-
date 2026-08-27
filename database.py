"""Асинхронный слой работы с SQLite."""

from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    username   TEXT,
    full_name  TEXT,
    phone      TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    price       REAL NOT NULL,
    photo_id    TEXT,
    stock       INTEGER NOT NULL DEFAULT 999,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INTEGER NOT NULL DEFAULT 1,
    UNIQUE(user_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    total          REAL NOT NULL,
    name           TEXT,
    phone          TEXT,
    address        TEXT,
    comment        TEXT,
    payment_method TEXT,
    status         TEXT NOT NULL DEFAULT 'new',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER,
    title      TEXT NOT NULL,
    price      REAL NOT NULL,
    quantity   INTEGER NOT NULL
);
"""


@asynccontextmanager
async def db():
    conn = await aiosqlite.connect(settings.db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        await conn.commit()
    finally:
        await conn.close()


async def init_db() -> None:
    async with db() as conn:
        await conn.executescript(SCHEMA)


# ---------------------------------------------------------------- пользователи

async def upsert_user(tg_id: int, username: str | None, full_name: str) -> None:
    async with db() as conn:
        await conn.execute(
            """INSERT INTO users (tg_id, username, full_name, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(tg_id) DO UPDATE SET username=?, full_name=?""",
            (tg_id, username, full_name, datetime.now().isoformat(timespec="seconds"),
             username, full_name),
        )


async def all_user_ids() -> list[int]:
    async with db() as conn:
        rows = await (await conn.execute("SELECT tg_id FROM users")).fetchall()
    return [r["tg_id"] for r in rows]


# ------------------------------------------------------------------ категории

async def get_categories(only_active: bool = True) -> list[dict]:
    sql = "SELECT * FROM categories"
    if only_active:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY id"
    async with db() as conn:
        rows = await (await conn.execute(sql)).fetchall()
    return [dict(r) for r in rows]


async def get_category(cat_id: int) -> dict | None:
    async with db() as conn:
        row = await (await conn.execute(
            "SELECT * FROM categories WHERE id = ?", (cat_id,))).fetchone()
    return dict(row) if row else None


async def add_category(title: str) -> int:
    async with db() as conn:
        cur = await conn.execute("INSERT INTO categories (title) VALUES (?)", (title,))
        return cur.lastrowid


async def delete_category(cat_id: int) -> None:
    async with db() as conn:
        await conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))


# --------------------------------------------------------------------- товары

async def get_products(cat_id: int, only_active: bool = True) -> list[dict]:
    sql = "SELECT * FROM products WHERE category_id = ?"
    if only_active:
        sql += " AND is_active = 1 AND stock > 0"
    sql += " ORDER BY id"
    async with db() as conn:
        rows = await (await conn.execute(sql, (cat_id,))).fetchall()
    return [dict(r) for r in rows]


async def get_product(product_id: int) -> dict | None:
    async with db() as conn:
        row = await (await conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,))).fetchone()
    return dict(row) if row else None


async def add_product(category_id: int, title: str, description: str,
                      price: float, photo_id: str | None, stock: int = 999) -> int:
    async with db() as conn:
        cur = await conn.execute(
            """INSERT INTO products (category_id, title, description, price, photo_id, stock)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (category_id, title, description, price, photo_id, stock),
        )
        return cur.lastrowid


async def toggle_product(product_id: int) -> None:
    async with db() as conn:
        await conn.execute(
            "UPDATE products SET is_active = 1 - is_active WHERE id = ?", (product_id,))


async def delete_product(product_id: int) -> None:
    async with db() as conn:
        await conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


# ------------------------------------------------------------------- корзина

async def add_to_cart(user_id: int, product_id: int, qty: int = 1) -> None:
    async with db() as conn:
        await conn.execute(
            """INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)
               ON CONFLICT(user_id, product_id)
               DO UPDATE SET quantity = quantity + ?""",
            (user_id, product_id, qty, qty),
        )


async def change_qty(user_id: int, product_id: int, delta: int) -> None:
    async with db() as conn:
        await conn.execute(
            "UPDATE cart_items SET quantity = quantity + ? WHERE user_id = ? AND product_id = ?",
            (delta, user_id, product_id),
        )
        await conn.execute(
            "DELETE FROM cart_items WHERE user_id = ? AND quantity <= 0", (user_id,))


async def remove_from_cart(user_id: int, product_id: int) -> None:
    async with db() as conn:
        await conn.execute(
            "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user_id, product_id))


async def clear_cart(user_id: int) -> None:
    async with db() as conn:
        await conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))


async def get_cart(user_id: int) -> list[dict]:
    async with db() as conn:
        rows = await (await conn.execute(
            """SELECT c.product_id, c.quantity, p.title, p.price, p.stock
               FROM cart_items c JOIN products p ON p.id = c.product_id
               WHERE c.user_id = ? ORDER BY c.id""",
            (user_id,))).fetchall()
    return [dict(r) for r in rows]


def cart_total(items: list[dict]) -> float:
    return sum(i["price"] * i["quantity"] for i in items)


# -------------------------------------------------------------------- заказы

async def create_order(user_id: int, data: dict, items: list[dict]) -> int:
    total = cart_total(items)
    async with db() as conn:
        cur = await conn.execute(
            """INSERT INTO orders
               (user_id, total, name, phone, address, comment, payment_method, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
            (user_id, total, data.get("name"), data.get("phone"), data.get("address"),
             data.get("comment"), data.get("payment"),
             datetime.now().isoformat(timespec="seconds")),
        )
        order_id = cur.lastrowid
        for it in items:
            await conn.execute(
                """INSERT INTO order_items (order_id, product_id, title, price, quantity)
                   VALUES (?, ?, ?, ?, ?)""",
                (order_id, it["product_id"], it["title"], it["price"], it["quantity"]),
            )
            await conn.execute(
                "UPDATE products SET stock = MAX(stock - ?, 0) WHERE id = ?",
                (it["quantity"], it["product_id"]),
            )
        await conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return order_id


async def get_order(order_id: int) -> dict | None:
    async with db() as conn:
        row = await (await conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,))).fetchone()
        if not row:
            return None
        items = await (await conn.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order_id,))).fetchall()
    order = dict(row)
    order["items"] = [dict(i) for i in items]
    return order


async def get_user_orders(user_id: int, limit: int = 10) -> list[dict]:
    async with db() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit))).fetchall()
    return [dict(r) for r in rows]


async def get_orders(limit: int = 20) -> list[dict]:
    async with db() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))).fetchall()
    return [dict(r) for r in rows]


async def set_status(order_id: int, status: str) -> None:
    async with db() as conn:
        await conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))


async def get_stats() -> dict:
    async with db() as conn:
        users = (await (await conn.execute("SELECT COUNT(*) c FROM users")).fetchone())["c"]
        products = (await (await conn.execute("SELECT COUNT(*) c FROM products")).fetchone())["c"]
        orders = (await (await conn.execute("SELECT COUNT(*) c FROM orders")).fetchone())["c"]
        revenue = (await (await conn.execute(
            "SELECT COALESCE(SUM(total), 0) s FROM orders WHERE status != 'cancelled'"
        )).fetchone())["s"]
        new_orders = (await (await conn.execute(
            "SELECT COUNT(*) c FROM orders WHERE status = 'new'")).fetchone())["c"]
    return {"users": users, "products": products, "orders": orders,
            "revenue": revenue, "new_orders": new_orders}
