"""Сквозная проверка покупательского сценария: старт → каталог → корзина → заказ."""

import pytest

import database as db
from conftest import USER_ID, callback_update, text_update


@pytest.fixture
async def catalog(db_file):
    cat_id = await db.add_category("☕ Кофе")
    p1 = await db.add_product(cat_id, "Эфиопия", "Цитрус и жасмин", 890, None, stock=10)
    p2 = await db.add_product(cat_id, "Бразилия", "Шоколад и орех", 690, None, stock=10)
    return {"cat": cat_id, "p1": p1, "p2": p2}


async def test_start_registers_user(dp, bot, session):
    await dp.feed_update(bot, text_update("/start"))
    assert "Добро пожаловать" in session.last_text()
    assert USER_ID in await db.all_user_ids()


async def test_catalog_and_product_card(dp, bot, session, catalog):
    await dp.feed_update(bot, text_update("🛍 Каталог"))
    assert "Выберите категорию" in session.last_text()

    session.clear()
    await dp.feed_update(bot, callback_update(f"cat_{catalog['cat']}"))
    assert "Выберите товар" in session.last_text()

    session.clear()
    await dp.feed_update(bot, callback_update(f"prod_{catalog['p1']}"))
    assert "Эфиопия" in session.last_text()
    assert "890" in session.last_text()


async def test_cart_add_change_and_total(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"add_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update(f"add_{catalog['p2']}"))
    assert len(await db.get_cart(USER_ID)) == 2

    session.clear()
    await dp.feed_update(bot, text_update("🛒 Корзина"))
    assert "Итого" in session.last_text()

    await dp.feed_update(bot, callback_update(f"plus_{catalog['p1']}"))
    cart = {i["product_id"]: i["quantity"] for i in await db.get_cart(USER_ID)}
    assert cart[catalog["p1"]] == 2

    await dp.feed_update(bot, callback_update(f"minus_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update(f"del_{catalog['p2']}"))
    cart = await db.get_cart(USER_ID)
    assert len(cart) == 1 and cart[0]["quantity"] == 1


async def test_full_checkout_creates_order_and_notifies_admin(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"add_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван Тестов"))
    await dp.feed_update(bot, text_update("+79991234567"))
    await dp.feed_update(bot, text_update("Москва, ул. Ленина, 1, кв. 2"))
    await dp.feed_update(bot, text_update("-"))

    session.clear()
    await dp.feed_update(bot, callback_update("pay_cash"))
    assert "Проверьте заказ" in session.last_text()

    session.clear()
    await dp.feed_update(bot, callback_update("confirm_order"))

    orders = await db.get_user_orders(USER_ID)
    assert len(orders) == 1
    order = await db.get_order(orders[0]["id"])
    assert order["name"] == "Иван Тестов"
    assert order["phone"] == "+79991234567"
    assert order["payment_method"] == "cash"
    assert order["total"] == 890
    assert order["items"][0]["title"] == "Эфиопия"

    # корзина очищена, склад уменьшен, админ уведомлён
    assert await db.get_cart(USER_ID) == []
    assert (await db.get_product(catalog["p1"]))["stock"] == 9
    admin_msgs = [c for c in session.named("SendMessage") if c.chat_id == 1000]
    assert admin_msgs and "Новый заказ" in admin_msgs[-1].text


async def test_checkout_rejects_short_phone(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"add_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван"))
    session.clear()
    await dp.feed_update(bot, text_update("123"))
    assert "номер неполный" in session.last_text()


async def test_my_orders_shows_status(dp, bot, session, catalog):
    order_id = await db.create_order(
        USER_ID, {"name": "И", "phone": "+7", "address": "а", "payment": "cash"},
        [{"product_id": catalog["p1"], "title": "Эфиопия", "price": 890, "quantity": 1}])
    session.clear()
    await dp.feed_update(bot, text_update("📦 Мои заказы"))
    assert f"#{order_id}" in session.last_text()
    assert "Новый" in session.last_text()
