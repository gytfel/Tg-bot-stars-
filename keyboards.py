"""Все клавиатуры бота."""

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from utils import MANUAL_STATUSES, PAYMENTS, STATUSES, money


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    if settings.stars_shop:
        rows = [
            [KeyboardButton(text="⭐ Купить звёзды")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="ℹ️ О магазине")],
        ]
    else:
        rows = [
            [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="🛒 Корзина")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="ℹ️ О магазине")],
        ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def phone_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
                  [KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)


# ------------------------------------------------------------------- каталог

def categories_kb(categories: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c["title"], callback_data=f"cat_{c['id']}")
    kb.adjust(2)
    return kb.as_markup()


def products_kb(products: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p['title']} — {money(p['price'])}",
                  callback_data=f"prod_{p['id']}")
    kb.button(text="⬅️ К категориям", callback_data="catalog")
    kb.adjust(1)
    return kb.as_markup()


def product_kb(product: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 В корзину", callback_data=f"add_{product['id']}")
    kb.button(text="⬅️ Назад", callback_data=f"cat_{product['category_id']}")
    kb.adjust(1)
    return kb.as_markup()


# ------------------------------------------------------------------- корзина

def cart_kb(items: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i in items:
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"minus_{i['product_id']}"),
            InlineKeyboardButton(text=f"{i['title'][:18]} ×{i['quantity']}",
                                 callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"plus_{i['product_id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{i['product_id']}"),
        )
    kb.row(InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout"))
    kb.row(InlineKeyboardButton(text="🧹 Очистить", callback_data="clear_cart"),
           InlineKeyboardButton(text="🛍 В каталог", callback_data="catalog"))
    return kb.as_markup()


def payment_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.online_enabled:
        kb.button(text=PAYMENTS["online"], callback_data="pay_online")
    # «при получении» бессмысленно для цифрового товара — получения нет
    if not settings.digital:
        kb.button(text=PAYMENTS["cash"], callback_data="pay_cash")
    kb.button(text=PAYMENTS["transfer"], callback_data="pay_transfer")
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="confirm_order")
    kb.button(text="❌ Отменить", callback_data="cancel_order")
    kb.adjust(2)
    return kb.as_markup()


# --------------------------------------------------------------------- админ

def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📂 Категории", callback_data="a_cats")
    kb.button(text="📦 Товары", callback_data="a_prods")
    kb.button(text="🧾 Заказы", callback_data="a_orders")
    kb.button(text="📊 Статистика", callback_data="a_stats")
    kb.button(text="📣 Рассылка", callback_data="a_broadcast")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def admin_cats_kb(categories: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.row(
            InlineKeyboardButton(text=c["title"], callback_data="noop"),
            InlineKeyboardButton(text="🗑", callback_data=f"a_delcat_{c['id']}"),
        )
    kb.row(InlineKeyboardButton(text="➕ Добавить категорию", callback_data="a_addcat"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="a_menu"))
    return kb.as_markup()


def admin_pick_cat_kb(categories: list[dict], prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c["title"], callback_data=f"{prefix}_{c['id']}")
    kb.button(text="⬅️ Назад", callback_data="a_menu")
    kb.adjust(2)
    return kb.as_markup()


def admin_prods_kb(products: list[dict], cat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        mark = "🟢" if p["is_active"] else "🔴"
        kb.row(
            InlineKeyboardButton(text=f"{mark} {p['title']} — {money(p['price'])}",
                                 callback_data=f"a_toggle_{p['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"a_delprod_{p['id']}"),
        )
    kb.row(InlineKeyboardButton(text="➕ Добавить товар",
                                callback_data=f"a_addprod_{cat_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="a_prods"))
    return kb.as_markup()


def admin_orders_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(
            text=f"#{o['id']} · {money(o['total'])} · {STATUSES.get(o['status'], o['status'])}",
            callback_data=f"a_order_{o['id']}")
    kb.button(text="⬅️ Назад", callback_data="a_menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_order_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, label in MANUAL_STATUSES.items():
        kb.button(text=label, callback_data=f"a_status_{order_id}_{code}")
    kb.button(text="⬅️ К заказам", callback_data="a_orders")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def back_admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="a_menu")
    return kb.as_markup()


# ------------------------------------------------------------- покупка звёзд

def star_packages_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for quantity in settings.star_packages:
        kb.button(text=f"{quantity} ⭐ · {money(quantity * settings.star_price)}",
                  callback_data=f"st_qty_{quantity}")
    kb.button(text="✏️ Другое количество", callback_data="st_custom")
    kb.adjust(2)
    return kb.as_markup()


def star_recipient_kb(username: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if username:
        kb.button(text=f"Себе (@{username})", callback_data="st_me")
    kb.button(text="⬅️ Изменить количество", callback_data="st_start")
    kb.adjust(1)
    return kb.as_markup()


def star_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Оплатить в TON", callback_data="st_pay")
    kb.button(text="❌ Отменить", callback_data="st_cancel")
    kb.adjust(1)
    return kb.as_markup()


def ton_invoice_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Я оплатил, проверить", callback_data=f"st_check_{order_id}")
    kb.button(text="❌ Отменить заказ", callback_data=f"st_drop_{order_id}")
    kb.adjust(1)
    return kb.as_markup()


def admin_star_order_kb(order_id: int) -> InlineKeyboardMarkup:
    """Кнопки под задачей «купить вручную»."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Купил, зачислено", callback_data=f"a_stdone_{order_id}")
    kb.button(text="🔁 Повторить автозакупку", callback_data=f"a_stretry_{order_id}")
    kb.adjust(1)
    return kb.as_markup()
